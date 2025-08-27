from flask import Flask, render_template, request, jsonify
import database as db
import boto3
import json
import os
import requests

app = Flask(__name__)

# Initialize the database
db.init_db()

# --- Tool Definition: Google Search (Live) ---
def google_search(query):
    """Performs a real Google search using the Custom Search JSON API."""
    api_key = os.environ.get("GOOGLE_API_KEY")
    search_engine_id = os.environ.get("GOOGLE_CX")

    if not api_key or not search_engine_id:
        return "Error: Google API credentials not configured."

    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        "key": api_key,
        "cx": search_engine_id,
        "q": query,
        "num": 5 # Request top 5 results
    }

    try:
        response = requests.get(url, params=params)
        response.raise_for_status() # Raise an exception for bad status codes
        search_results = response.json()
        
        snippets = []
        if "items" in search_results:
            for item in search_results["items"]:
                title = item.get("title", "")
                link = item.get("link", "")
                snippet = item.get("snippet", "").replace("\n", " ")
                snippets.append(f'Title: {title}\nLink: {link}\nSnippet: {snippet}')
        
        if not snippets:
            return "No relevant search results found."

        return "\n\n".join(snippets)

    except requests.exceptions.RequestException as e:
        return f"Error during search API call: {e}"
    except Exception as e:
        return f"An unexpected error occurred: {e}"

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
        
        max_turns = 3
        for turn in range(max_turns):
            conversation_history = db.get_conversation(conversation_id)["messages"]
            
            system_prompt = '''You are a helpful assistant. If you need to find out recent information or anything you don't know, you can use the google_search tool. To use it, you MUST respond with a JSON object containing 'tool_name': 'google_search' and 'query': 'your search query'. Do not add any other text. If you have enough information to answer, provide the answer directly.'''

            body = ""
            if "anthropic" in model:
                body = json.dumps({
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 1024,
                    "system": system_prompt,
                    "messages": conversation_history
                })
            else:
                if turn > 0:
                    system_prompt = "You are a helpful assistant."
                prompt = f"{system_prompt}\n\n"
                for msg in conversation_history:
                    role = "Human" if msg['role'] == 'user' else "Assistant"
                    prompt += f"{role}: {msg['content']}\n"
                prompt += "Assistant:"
                body = json.dumps({"prompt": prompt, "max_tokens": 1024})

            response = bedrock_runtime.invoke_model(
                body=body, modelId=model, accept="application/json", contentType="application/json"
            )
            response_body = json.loads(response.get("body").read())

            if "anthropic" in model:
                llm_response = response_body.get('content', [{}])[0].get('text', "")
            else:
                llm_response = response_body.get('completion', str(response_body))

            try:
                tool_call = json.loads(llm_response)
                if tool_call.get("tool_name") == "google_search":
                    search_query = tool_call.get("query")
                    search_results = google_search(search_query)
                    db.add_message(conversation_id, "assistant", llm_response)
                    db.add_message(conversation_id, "user", f"Search results for \"{search_query}\": {search_results}")
                    continue
                else:
                    break
            except (json.JSONDecodeError, AttributeError):
                break

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
