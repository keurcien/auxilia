import requests

BASE_URL = "http://localhost:8000"


def create_user():
    user_data = {
        "name": "Keurcien",
        "email": "keurcien@gmail.com",
        "password_hash": "testpassword",
        "is_admin": True,
    }
    response = requests.post(f"{BASE_URL}/users", json=user_data)
    user_id = response.json()["id"]
    return user_id


def create_agent(user_id):
    agent_data = {
        "name": "Data Analyst",
        "instructions": "You are a data analyst. You are given a dataset and you need to analyze it.",
        "owner_id": user_id,
    }
    response = requests.post(f"{BASE_URL}/agents", json=agent_data)
    agent_id = response.json()["id"]
    return agent_id


def create_mcp_server():
    mcp_server_data = {
        "name": "DeepWiki",
        "url": "https://mcp.deepwiki.com/mcp",
        "icon_url": "https://storage.googleapis.com/choose-assets/deepwiki.png",
        "auth_type": "none",
    }
    response = requests.post(f"{BASE_URL}/mcp-servers", json=mcp_server_data)
    mcp_server_id = response.json()["id"]
    return mcp_server_id


def create_agent_mcp_server_binding(agent_id, mcp_server_id):
    agent_mcp_server_binding_data = {
        "agent_id": agent_id,
        "mcp_server_id": mcp_server_id,
        "enabled_tools": ["read_wiki_structure"],
    }
    response = requests.post(
        f"{BASE_URL}/agents/{agent_id}/mcp-servers/{mcp_server_id}",
        json=agent_mcp_server_binding_data,
    )
    return response.json()


if __name__ == "__main__":
    user_id = create_user()
    agent_id = create_agent(user_id)
    mcp_server_id = create_mcp_server()
    create_agent_mcp_server_binding(agent_id, mcp_server_id)
