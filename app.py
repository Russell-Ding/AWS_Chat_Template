from flask import Flask, render_template, request, jsonify
import database as db
import boto3
import json

app = Flask(__name__)

# Initialize the database
db.init_db()

@app.route("/")
def index():
    conversations = db.get_conversations()
    return render_template("index.html", conversations=conversations)

@app.route("/conversation/<int:conversation_id>")
def get_conversation_route(conversation_id):
    conversation = db.get_conversation(conversation_id)
    if conversation:
        return jsonify(conversation)
    return jsonify({"error": "Conversation not found"}), 404

@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    message = data.get("message")
    model = data.get("model")
    conversation_id = data.get("conversation_id")
    new_conversation_info = None

    if not conversation_id:
        conversation_name = f"Conversation about {message[:20]}..."
        conversation_id = db.create_conversation(name=conversation_name, model=model)
        new_conversation_info = {"id": conversation_id, "name": conversation_name}

    db.add_message(conversation_id, "user", message)

    llm_response = ""
    try:
        bedrock_runtime = boto3.client(service_name='bedrock-runtime')
        conversation_history = db.get_conversation(conversation_id)["messages"]

        # --- Prepare the payload based on the model provider ---
        body = ""
        if "anthropic" in model:
            body = json.dumps({
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 1024,
                "messages": conversation_history
            })
        elif "deepseek" in model:
            # DeepSeek uses a format similar to the standard chat messages API
            body = json.dumps({
                "messages": conversation_history,
                "max_tokens": 1024
            })
        elif "amazon.titan" in model:
            prompt = ""
            for msg in conversation_history:
                role = "user" if msg['role'] == 'user' else "bot"
                prompt += f"{role}: {msg['content']}\n"
            prompt += "bot:"
            body = json.dumps({
                "inputText": prompt,
                "textGenerationConfig": {"maxTokenCount": 1024}
            })
        else:
            raise ValueError(f"Unsupported model provider for model ID: {model}")

        # --- Invoke the model ---
        response = bedrock_runtime.invoke_model(
            body=body, modelId=model, accept="application/json", contentType="application/json"
        )
        response_body = json.loads(response.get("body").read())

        # --- Parse the response to extract the text ---
        if "anthropic" in model:
            llm_response = response_body.get('content', [{}])[0].get('text', "Error: No text found")
        elif "deepseek" in model:
            llm_response = response_body.get('choices')[0].get('message').get('content')
        elif "amazon.titan" in model:
            llm_response = response_body.get("results")[0].get("outputText", "Error: No output text found")
        else:
            llm_response = f"Error: Response parsing not implemented for this model."

    except Exception as e:
        llm_response = f"Error communicating with Bedrock: {e}"

    db.add_message(conversation_id, "assistant", llm_response)

    response_data = {
        "conversation_id": conversation_id,
        "messages": db.get_conversation(conversation_id)["messages"],
    }
    if new_conversation_info:
        response_data["new_conversation"] = new_conversation_info

    return jsonify(response_data)

if __name__ == "__main__":
    app.run(debug=True)
