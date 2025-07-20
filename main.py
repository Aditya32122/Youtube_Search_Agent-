import streamlit as st
import requests
import json
from datetime import datetime
from typing import Dict, List, Optional

# Configure Streamlit page
st.set_page_config(
    page_title="Agent API Frontend",
    page_icon="🤖",
    layout="wide"
)

# Configuration
API_BASE_URL = st.sidebar.text_input("API Base URL", value="http://localhost:8000")

# Session state initialization
if 'current_session' not in st.session_state:
    st.session_state.current_session = None
if 'messages' not in st.session_state:
    st.session_state.messages = []
if 'apps' not in st.session_state:
    st.session_state.apps = []

def make_api_request(endpoint: str, method: str = "GET", data: Dict = None, stream: bool = False) -> Optional[Dict]:
    """Make API request with error handling and streaming support"""
    try:
        url = f"{API_BASE_URL}{endpoint}"
        headers = {'Content-Type': 'application/json'}
        
        if method == "POST":
            if stream:
                url = f"{API_BASE_URL}/run_sse"
            response = requests.post(url, json=data, headers=headers, stream=stream)
        else:
            response = requests.request(method, url, headers=headers)
        
        response.raise_for_status()
        
        if stream:
            return response
        return response.json() if response.content else {}
    except requests.exceptions.RequestException as e:
        st.error(f"API Error: {str(e)}")
        return None

def process_sse_events(response):
    """Process Server-Sent Events from response"""
    formatted_events = []
    current_event = None
    
    try:
        for line in response.iter_lines():
            if line:
                line = line.decode('utf-8')
                if line.startswith('data: '):
                    try:
                        event_data = json.loads(line[6:])
                        if event_data.get('content', {}).get('parts'):
                            for part in event_data['content']['parts']:
                                if part.get('functionCall'):
                                    current_event = {
                                        'type': 'function_call',
                                        'content': part['functionCall'],
                                        'role': 'assistant',
                                        'name': part['functionCall'].get('name'),
                                        'args': part['functionCall'].get('args')
                                    }
                                elif part.get('functionResponse'):
                                    response_data = part['functionResponse']
                                    if response_data.get('name') == 'search_youtube_videos':
                                        videos = response_data.get('response', {}).get('videos', [])
                                        current_event = {
                                            'type': 'video_list',
                                            'content': videos,
                                            'role': 'assistant'
                                        }
                                elif part.get('text'):
                                    if current_event and current_event.get('type') == 'text':
                                        current_event['content'] += part['text']
                                    else:
                                        current_event = {
                                            'type': 'text',
                                            'content': part['text'],
                                            'role': 'assistant'
                                        }
                            
                            if not event_data.get('partial') and current_event:
                                formatted_events.append(current_event)
                                current_event = None
                                
                    except json.JSONDecodeError:
                        continue
    except Exception as e:
        st.error(f"Error processing SSE events: {str(e)}")
    
    return formatted_events

def load_apps():
    """Load available apps"""
    apps = make_api_request("/list-apps")
    if apps:
        st.session_state.apps = apps
        return apps
    return []

def create_session(app_name: str, user_id: str, initial_state: Dict = None):
    """Create a new session"""
    data = initial_state or {}
    session = make_api_request(f"/apps/{app_name}/users/{user_id}/sessions", "POST", data)
    if session:
        st.session_state.current_session = session
        st.session_state.messages = []
        return session
    return None

def format_video_response(video: Dict) -> Dict:
    """Format a video response with metadata"""
    return {
        "type": "video",
        "video_id": video.get('videoId'),
        "title": video.get('title'),
        "description": video.get('description'),
        "thumbnail": video.get('thumbnail'),
        "channel": video.get('channel'),
        "url": video.get('url'),
        "publishedAt": video.get('publishedAt')
    }

def send_message(app_name: str, user_id: str, session_id: str, message: str):
    """Send a message to the agent and format video responses"""
    data = {
        "app_name": app_name,
        "user_id": user_id,
        "session_id": session_id,
        "new_message": {
            "parts": [{"text": message}],
            "role": "user"
        },
        "streaming": True
    }
    
    response = make_api_request("/run", "POST", data, stream=True)
    if response:
        return process_sse_events(response)
    return []

def list_sessions(app_name: str, user_id: str):
    """List sessions for a user"""
    sessions = make_api_request(f"/apps/{app_name}/users/{user_id}/sessions")
    return sessions or []

def load_session(app_name: str, user_id: str, session_id: str):
    """Load a specific session"""
    session = make_api_request(f"/apps/{app_name}/users/{user_id}/sessions/{session_id}")
    if session:
        st.session_state.current_session = session
        messages = []
        for event in session.get('events', []):
            if event.get('content') and event.get('content', {}).get('parts'):
                for part in event['content']['parts']:
                    if part.get('function_response'):
                        response = part['function_response'].get('response', {})
                        if response.get('videos'):
                            messages.append({
                                'type': 'video_list',
                                'content': response['videos'],
                                'role': event.get('author', 'assistant'),
                                'timestamp': event.get('timestamp', 0)
                            })
                    elif part.get('text'):
                        messages.append({
                            'type': 'text',
                            'content': part['text'],
                            'role': event.get('author', 'unknown'),
                            'timestamp': event.get('timestamp', 0)
                        })
        st.session_state.messages = messages
    return session

def extract_youtube_id(url: str) -> Optional[str]:
    """Extract YouTube video ID from URL"""
    if "youtube.com/watch?v=" in url:
        return url.split("watch?v=")[1].split("&")[0]
    elif "youtu.be/" in url:
        return url.split("youtu.be/")[1].split("?")[0]
    return None

def display_event(event: Dict):
    """Display a single event in the chat interface"""
    if not event:
        return
        
    with st.chat_message("assistant"):
        if event['type'] == 'function_call':
            st.markdown(f"🔄 **Function Call:** `{event.get('name', '')}`")
            if event.get('args'):
                st.code(json.dumps(event['args'], indent=2), language='json')
                
        elif event['type'] == 'video_list':
            st.write("Here are the relevant videos:")
            for video in event['content']:
                col1, col2 = st.columns([1, 3])
                with col1:
                    if video.get('thumbnail'):
                        st.image(video['thumbnail'], use_container_width=True)
                with col2:
                    st.markdown(f"**[{video.get('title', '')}]({video.get('url', '')})**")
                    st.markdown(f"**Channel:** {video.get('channel', '')}")
                    if video.get('description'):
                        st.markdown(f"_{video.get('description')[:150]}..._")
                    published = video.get('publishedAt')
                    if published:
                        try:
                            dt = datetime.fromisoformat(published.replace('Z', '+00:00'))
                            st.markdown(f"**Published:** {dt.strftime('%Y-%m-%d')}")
                        except Exception:
                            pass
                st.markdown("---")
                
        elif event['type'] == 'function_response':
            st.markdown(f"✅ **Function Response:** `{event.get('name', '')}`")
            if event.get('content'):
                st.code(json.dumps(event['content'], indent=2), language='json')
                
        else:  # text type
            st.write(event.get('content', ''))

# Main UI
st.title("🤖 Agent API Frontend")

# Sidebar for configuration
st.sidebar.header("Configuration")

# Load apps
if st.sidebar.button("Refresh Apps"):
    load_apps()

if not st.session_state.apps:
    load_apps()

# App selection
selected_app = st.sidebar.selectbox("Select App", st.session_state.apps or ["No apps available"])

# User ID input
user_id = st.sidebar.text_input("User ID", value="user123")

# Session management section
st.sidebar.header("Session Management")

if selected_app and user_id:
    # List existing sessions
    if st.sidebar.button("Load Sessions"):
        sessions = list_sessions(selected_app, user_id)
        if sessions:
            session_options = [f"{s['id']} ({datetime.fromtimestamp(s.get('last_update_time', 0)).strftime('%Y-%m-%d %H:%M')})" 
                             for s in sessions]
            selected_session = st.sidebar.selectbox("Existing Sessions", session_options)
            if selected_session:
                session_id = selected_session.split(' ')[0]
                if st.sidebar.button("Load Selected Session"):
                    load_session(selected_app, user_id, session_id)

    # Create new session
    if st.sidebar.button("New Session"):
        session = create_session(selected_app, user_id)
        if session:
            st.sidebar.success(f"Created session: {session['id']}")

# Main chat interface
if st.session_state.current_session:
    session = st.session_state.current_session
    
    # Session info
    st.subheader(f"Session: {session['id']}")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.info(f"App: {session.get('app_name')}")
    with col2:
        st.info(f"User: {session.get( 'user_id')}")
    with col3:
        last_update = datetime.fromtimestamp(session.get('last_update_time', 0))
        st.info(f"Last Update: {last_update.strftime('%Y-%m-%d %H:%M')}")

    # Display chat messages
    chat_container = st.container()
    with chat_container:
        for message in st.session_state.messages:
            role = message.get('role')
            content = message.get('content')
            msg_type = message.get('type', 'text')
            
            if role == 'user':
                with st.chat_message("user"):
                    st.write(content)
            else:
                with st.chat_message("assistant"):
                    if msg_type == 'video_list':
                        st.write("Here are the relevant videos:")
                        for video in content:
                            col1, col2 = st.columns([1, 3])
                            with col1:
                                if video.get('thumbnail'):
                                    st.image(video['thumbnail'], use_container_width=True)
                            with col2:
                                # Show clickable title as a YouTube link
                                st.markdown(f"**[{video.get('title', '')}]({video.get('url', '')})**")
                                st.markdown(f"**Channel:** {video.get('channel', '')}")
                                if video.get('description'):
                                    st.markdown(f"_{video.get('description')[:150]}..._")
                                # Published date (safe fallback)
                                published = video.get('publishedAt')
                                if published:
                                    try:
                                        dt = datetime.fromisoformat(published.replace('Z', '+00:00'))
                                        st.markdown(f"**Published:** {dt.strftime('%Y-%m-%d')}")
                                    except Exception:
                                        pass
                            st.markdown("---")
                    else:
                        st.write(content)

    # Message input
    if prompt := st.chat_input("Type your message here..."):
        # Add user message to chat
        st.session_state.messages.append({
            'role': 'user',
            'content': prompt,
            'timestamp': datetime.now().timestamp()
        })
        
        # Display user message immediately
        with st.chat_message("user"):
            st.write(prompt)
        
        # Send to API and get response
        with st.spinner("Getting response..."):
            events = send_message(session['appName'], session['userId'], session['id'], prompt)
            
            if events:
                for event in events:
                    if isinstance(event, dict) and 'type' in event:
                        st.session_state.messages.append({
                            'role': event.get('author', 'assistant'),
                            'content': event.get('content'),
                            'text': event.get('text', ''),
                            'type': event.get('type'),
                            'timestamp': event.get('timestamp', datetime.now().timestamp())
                        })
                        
                        display_event(event)

        # Refresh the page to show updated messages
        st.rerun()

else:
    st.info("Please select an app, enter a user ID, and create or load a session to start chatting.")

# Additional features section
st.sidebar.header("Additional Features")

if st.session_state.current_session:
    session = st.session_state.current_session
    
    # Artifacts section
    if st.sidebar.button("List Artifacts"):
        artifacts = make_api_request(f"/apps/{session['app_name']}/users/{session['user_id']}/sessions/{session['id']}/artifacts")
        if artifacts:
            st.sidebar.write("Artifacts:")
            for artifact in artifacts:
                st.sidebar.write(f"- {artifact}")
    
    # Session state display
    if st.sidebar.button("Show Session State"):
        with st.expander("Session State"):
            st.json(session.get('state', {}))

# Debug section
if st.sidebar.checkbox("Debug Mode"):
    st.sidebar.header("Debug Info")
    if st.session_state.current_session:
        st.sidebar.json(st.session_state.current_session)
    
    st.sidebar.write("Messages:")
    st.sidebar.json(st.session_state.messages)

# Footer
st.markdown("---")
st.markdown("*Agent API Frontend - Built with Streamlit*")