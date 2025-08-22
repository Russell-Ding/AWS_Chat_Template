from flask import Flask, render_template, request, jsonify
import database as db

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
    # 1. Instantiate your Bedrock client here.
    # bedrock_client = ...

    # 2. Get the conversation history for the LLM.
    # conversation_history = db.get_conversation(conversation_id)["messages"]

    # 3. Format the history and send it to the Bedrock model.
    # response = bedrock_client.invoke_model(...) # This is an example call
    # llm_response = response["body"].read().decode("utf-8")

    # For now, we'll just echo the message back.
    llm_response = f"Echo from DB: {message}"
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
