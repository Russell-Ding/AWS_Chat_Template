from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

# In-memory store for conversations for simplicity.
# In a real application, you would use a database.
conversations = {}
conversation_order = []
conversation_id_counter = 0

@app.route("/")
def index():
    return render_template("index.html", conversations=conversations, conversation_order=conversation_order)

@app.route("/conversation/<conversation_id>")
def get_conversation(conversation_id):
    conversation = conversations.get(conversation_id)
    if conversation:
        return jsonify(conversation)
    return jsonify({"error": "Conversation not found"}), 404

@app.route("/chat", methods=["POST"])
def chat():
    global conversation_id_counter
    data = request.json
    message = data.get("message")
    model = data.get("model")
    conversation_id = data.get("conversation_id")
    new_conversation = False

    if not conversation_id:
        new_conversation = True
        conversation_id = str(conversation_id_counter)
        conversations[conversation_id] = {
            "id": conversation_id,
            "name": f"Conversation {conversation_id}",
            "messages": [],
            "model": model
        }
        conversation_order.insert(0, conversation_id)
        conversation_id_counter += 1

    # Add user message to conversation
    conversations[conversation_id]["messages"].append({"role": "user", "content": message})

    # Call to your LLM on AWS would go here
    # For now, we'll just echo the message back.
    llm_response = f"Echo: {message}"

    # Add assistant message to conversation
    conversations[conversation_id]["messages"].append({"role": "assistant", "content": llm_response})

    response = {
        "conversation_id": conversation_id,
        "messages": conversations[conversation_id]["messages"]
    }
    if new_conversation:
        response["new_conversation"] = {
            "id": conversation_id,
            "name": conversations[conversation_id]["name"]
        }

    return jsonify(response)

if __name__ == "__main__":
    app.run(debug=True)
