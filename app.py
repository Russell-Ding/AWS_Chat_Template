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

    # Add user message to the database
    db.add_message(conversation_id, "user", message)

    # --- AWS Bedrock Client Integration --- #
    llm_response = ""
    try:
        # 1. Instantiate Bedrock client. Ensure your AWS credentials are configured.
        bedrock_runtime = boto3.client(service_name='bedrock-runtime')

        # 2. Get conversation history and format it for the model.
        # Note: Prompt formatting can be model-specific. This is a generic example.
        conversation_history = db.get_conversation(conversation_id)["messages"]
        prompt = ""
        for msg in conversation_history:
            role = "Human" if msg['role'] == 'user' else "Assistant"
            prompt += f"\n\n{role}: {msg['content']}"
        prompt += "\n\nAssistant:"

        # 3. Prepare the payload based on the model provider.
        if "anthropic" in model:
            body = json.dumps({
                "prompt": prompt,
                "max_tokens_to_sample": 500,
            })
        elif "amazon.titan" in model:
            body = json.dumps({
                "inputText": prompt,
                "textGenerationConfig": {"maxTokenCount": 500}
            })
        else: # Fallback for other models, may need adjustment
            body = json.dumps({"prompt": prompt})

        # 4. Invoke the model
        response = bedrock_runtime.invoke_model(
            body=body, modelId=model, accept="application/json", contentType="application/json"
        )

        # 5. Parse the response to extract only the text. This is the key fix.
        response_body = json.loads(response.get("body").read())

        if "anthropic" in model:
            llm_response = response_body.get("completion", "Error: No completion found.")
        elif "amazon.titan" in model:
            llm_response = response_body.get("results")[0].get("outputText", "Error: No output text found.")
        else:
            llm_response = str(response_body)

    except Exception as e:
        llm_response = f"Error communicating with Bedrock: {e}"
    # --- End of AWS Bedrock Client Integration --- #

    # Add assistant message to the database
    db.add_message(conversation_id, "assistant", llm_response)

    response = {
        "conversation_id": conversation_id,
        "messages": db.get_conversation(conversation_id)["messages"],
    }
    if new_conversation_info:
        response["new_conversation"] = new_conversation_info

    return jsonify(response)

if __name__ == "__main__":
    app.run(debug=True)
