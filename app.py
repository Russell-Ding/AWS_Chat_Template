from flask import Flask, render_template, request, jsonify
import database as db
import boto3
import json
import os
import requests
from bs4 import BeautifulSoup

app = Flask(__name__)

# Initialize the database
db.init_db()

# --- Tool Definition: Google Search and Multi-Scrape ---
def google_search(query):
    """Performs a Google search, then scrapes the content of the top 3 results."""
    try:
        # Step 1: Get top 3 search results from Google
        api_key = os.environ.get("GOOGLE_API_KEY")
        search_engine_id = os.environ.get("GOOGLE_CX")
        if not api_key or not search_engine_id:
            return "Error: Google API credentials not configured."

        search_url = "https://www.googleapis.com/customsearch/v1"
        params = {"key": api_key, "cx": search_engine_id, "q": query, "num": 3}
        response = requests.get(search_url, params=params)
        response.raise_for_status()
        search_results = response.json()

        if not search_results.get("items"):
            return "No relevant search results found."

        # Step 2: Scrape content from each result
        all_scraped_content = []
        urls_to_scrape = [item["link"] for item in search_results["items"]]

        for url in urls_to_scrape:
            try:
                headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
                scrape_response = requests.get(url, headers=headers, timeout=10)
                scrape_response.raise_for_status()

                soup = BeautifulSoup(scrape_response.text, 'html.parser')
                paragraphs = soup.find_all('p')
                scraped_text = '\n'.join([p.get_text() for p in paragraphs])

                if scraped_text:
                    all_scraped_content.append(f"--- Content from {url} ---\n{scraped_text}")
                
            except requests.exceptions.RequestException as e:
                print(f"Could not scrape {url}: {e}")
            except Exception as e:
                print(f"An error occurred while scraping {url}: {e}")

        if not all_scraped_content:
            return "Could not extract meaningful content from any of the top search results."

        return "\n\n--- END OF SOURCE ---\n\n".join(all_scraped_content)

    except requests.exceptions.RequestException as e:
        return f"Error during Google Search API call: {e}"
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
                    "max_tokens": 4096, # Increased token limit for more content
                    "system": system_prompt,
                    "messages": conversation_history
                })
            else:
                prompt = "\n\n".join([f"{msg['role']}: {msg['content']}" for msg in conversation_history])
                body = json.dumps({"prompt": prompt, "max_tokens": 4096})

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
