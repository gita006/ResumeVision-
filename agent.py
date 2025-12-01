import os
import json
import traceback  # Import traceback module

# Authenticate with Google API Key (Colab-compatible)
try:
    from google.colab import userdata
    GOOGLE_API_KEY = userdata.get('GOOGLE_API_KEY')  # Retrieve from Colab secrets
    if not GOOGLE_API_KEY:
        raise ValueError("GOOGLE_API_KEY not found in Colab secrets. Please add it under 'Secrets' in Colab.")
    os.environ["GOOGLE_API_KEY"] = GOOGLE_API_KEY
    print("✅ Gemini API key setup complete.")
except ImportError:
    # Fallback if not in Colab (e.g., local or other env)
    GOOGLE_API_KEY = input("Enter your Google API Key: ").strip()
    if not GOOGLE_API_KEY:
        raise ValueError("GOOGLE_API_KEY is required.")
    os.environ["GOOGLE_API_KEY"] = GOOGLE_API_KEY
    print("✅ Gemini API key setup complete (manual input).")
except Exception as e:
    print(f"🔑 Authentication Error: {e}")
    raise

# Install required packages (run this in a separate cell if needed)
!pip install google-adk google-generativeai

# Install aiosqlite for async SQLite driver and pdfplumber for PDF parsing
!pip install aiosqlite pdfplumber

# Import ADK components
from typing import Any, Dict
from google.adk.agents import Agent, LlmAgent
from google.adk.apps.app import App, EventsCompactionConfig
from google.adk.models.google_llm import Gemini
from google.adk.sessions import DatabaseSessionService
from google.adk.runners import Runner
from google.adk.tools.tool_context import ToolContext
from google.genai import types

# Additional import and configuration as per Gemini API docs
import google.generativeai as genai
genai.configure(api_key=GOOGLE_API_KEY)  # Configure the genai client

print("✅ ADK components imported successfully.")

# Configure Retry Options
retry_config = types.HttpRetryOptions(
    attempts=5,
    exp_base=7,
    initial_delay=1,
    http_status_codes=[429, 500, 503, 504],
)

# Helper Functions (async) - Keeping this for general use, but demo will use inline calls
async def run_session(
    runner_instance: Runner,
    user_queries: list[str] | str = None,
    session_name: str = "default",
):
    print(f"\n### Session: {session_name}")
    app_name = runner_instance.app_name
    try:
        session = await session_service.create_session(
            app_name=app_name, user_id=USER_ID, session_id=session_name
        )
    except Exception as e:
        print(f"Session creation error: {e}")
        session = await session_service.get_session(
            app_name=app_name, user_id=USER_ID, session_id=session_name
        )
    if user_queries:
        if isinstance(user_queries, str):
            user_queries = [user_queries]
        for query in user_queries:
            print(f"\nUser > {query}")
            query = types.Content(role="user", parts=[types.Part(text=query)])
            try:
                async for event in runner_instance.run_async(
                    user_id=USER_ID, session_id=session.id, new_message=query
                ):
                    # Only process events that have content and content parts
                    if event.content and event.content.parts:
                        text = event.content.parts[0].text
                        if text and text != "None":
                            print(f"Assistant > {text}")
            except Exception as e:
                print(f"Error during query processing: {e}")
                traceback.print_exc()  # Print full traceback for debugging
    else:
        print("No queries!")

print("✅ Helper functions defined.")

# Define Custom Tools for Session State
def save_userinfo(
    tool_context: ToolContext, user_name: str, preferred_roles: str
) -> Dict[str, Any]:
    """
    Tool to save user name and preferred job roles in session state.
    """
    tool_context.state["user:name"] = user_name
    tool_context.state["user:preferred_roles"] = preferred_roles
    return {"status": "success"}

def retrieve_userinfo(tool_context: ToolContext) -> Dict[str, Any]:
    """
    Tool to retrieve user info from session state.
    """
    user_name = tool_context.state.get("user:name", "Not provided")
    preferred_roles = tool_context.state.get("user:preferred_roles", "Not specified")
    return {"user_name": user_name, "preferred_roles": preferred_roles}

def extract_candidate_info(
    tool_context: ToolContext, resume_text: str
) -> Dict[str, Any]:
    """
    Extracts key information from a resume, including name, graduation details,
    skills, and certifications.
    """
    # This is a simplified extraction; a real-world tool might use a more complex
    # LLM call or regex patterns to be more robust.
    prompt = f"""Extract the following information from the resume text:
- Candidate Name
- Graduation (Degree, University, Year)
- Skills (list them)
- Certifications (list them)

Format the output as a JSON object with keys: 'name', 'graduation', 'skills', 'certifications'.
If information is not found, use 'N/A'.

Resume Text:
{resume_text}
"""
    response = tool_context.model.generate_content(prompt)
    try:
        # Attempt to parse the response as JSON
        extracted_info = json.loads(response.text)
    except json.JSONDecodeError:
        # Fallback if the LLM doesn't return perfect JSON
        extracted_info = {
            "name": "N/A",
            "graduation": "N/A",
            "skills": "N/A",
            "certifications": "N/A",
            "raw_response": response.text  # Keep raw response for debugging
        }
    return extracted_info

print("✅ Tools created.")

# Configuration
APP_NAME = "resume_screener_app"
USER_ID = "default_user"
MODEL_NAME = "gemini-pro-latest"  # Changed model name to 'gemini-pro-latest'

# Create the agent
resume_agent = LlmAgent(
    model=Gemini(model=MODEL_NAME, retry_options=retry_config),
    name="resume_screener",
    description="""
A resume screening assistant. Check if the resume matches the job requirements. Respond clearly with 'Match: Yes' or 'Match: No'. If yes, provide a clean summary of the candidate details (name, graduation, skills, certifications) in a structured format. If no, just say 'You are not matched'.
Use tools to save/retrieve user info for personalization and to extract candidate information.
""",
    tools=[save_userinfo, retrieve_userinfo, extract_candidate_info],  # Added new tool
)

# App with Context Compaction
resume_app = App(
    name=APP_NAME,
    root_agent=resume_agent,
    events_compaction_config=None,  # Explicitly disable compaction
)

# Persistent Sessions
db_url = "sqlite+aiosqlite:///resume_sessions.db"  # Modified to use aiosqlite
session_service = DatabaseSessionService(db_url=db_url)

# Runner
runner = Runner(app=resume_app, session_service=session_service)

print("✅ Resume Screening Agent initialized with persistence and compaction!")

# Demo Function (async wrapper) with manual resume upload
async def demo_resume_screener():
    # Upload resume manually (Colab-specific)
    try:
        from google.colab import files
        print("Please upload your resume file (e.g., .txt or .pdf).")
        uploaded = files.upload()  # This will prompt for file upload
        if not uploaded:
            raise ValueError("No file uploaded.")
        file_name = list(uploaded.keys())[0]

        # Handle different file types
        if file_name.lower().endswith('.pdf'):
            try:
                import pdfplumber
                with pdfplumber.open(file_name) as pdf:
                    sample_resume = ""
                    for page in pdf.pages:
                        sample_resume += page.extract_text() + "\n"
                print("✅ PDF resume processed successfully.")
            except ImportError:
                print("pdfplumber not installed. Falling back to default resume. Install with `!pip install pdfplumber`")
                print("Using default sample resume.")
        else:  # Assume it's a text file
            with open(file_name, 'r') as f:
                sample_resume = f.read()
            print("✅ Text resume uploaded and read successfully.")

    except ImportError:
        # Fallback if not in Colab
        sample_resume = input("Paste your resume text here: ").strip()
        if not sample_resume:
            sample_resume = """
            Experienced software engineer with 5 years in Python, ML, and data science. Worked at XYZ Corp on AI projects.
            Skills: Python, TensorFlow, SQL.
            """
            print("Using default sample resume.")
    except Exception as e:
        print(f"Error uploading resume: {e}")
        # Changed sample resume to a matching one for demonstration
        sample_resume = """
        Candidate Name: John Doe
        Graduation: Master of Science in Computer Science, Stanford University, 2020
        Skills: Python, Machine Learning, TensorFlow, PyTorch, SQL, Data Analysis, Scikit-learn, AWS
        Certifications: AWS Certified Machine Learning Specialty, Google Cloud Professional Data Engineer
        Work Experience:
        Senior AI Engineer at Tech Innovations Inc. (2020-Present)
        - Developed and deployed machine learning models for fraud detection using Python and TensorFlow.
        - Led a team of data scientists in building predictive analytics solutions, improving model accuracy by 15%.
        - Designed and optimized data pipelines on AWS for large-scale data processing.
        """
        print("Using a default sample resume that matches the job description for demonstration.")

    # Sample job (can also be made dynamic if needed)
    sample_job = """
    Looking for a Python developer with machine learning experience for data-driven roles.
    """

    session_id = "resume_screening_session_02"
    print(f"\n### Session: {session_id}")
    try:
        session = await session_service.create_session(
            app_name=APP_NAME, user_id=USER_ID, session_id=session_id
        )
    except Exception as e:
        print(f"Session creation error: {e}")
        session = await session_service.get_session(
            app_name=APP_NAME, user_id=USER_ID, session_id=session_id
        )

    # Helper to run a single query and print response
    async def run_single_query(query_text: str):
        print(f"\nUser > {query_text}")
        query = types.Content(role="user", parts=[types.Part(text=query_text)])
        assistant_response = ""
        try:
            async for event in runner.run_async(
                user_id=USER_ID, session_id=session.id, new_message=query
            ):
                if event.content and event.content.parts:
                    text = event.content.parts[0].text
                    if text and text != "None":
                        print(f"Assistant > {text}")
                        assistant_response += text
        except Exception as e:
            print(f"Error during query processing: {e}")
            traceback.print_exc()
        return assistant_response.strip()

    # Query 1: User preference
    await run_single_query("Hi. I prefer roles in AI and data science.")

    # Modified Query: Check match and provide summary or rejection in clear format
    match_query = f"Check if this resume matches the job requirements: {sample_job}. Respond with 'Match: Yes' or 'Match: No'. If yes, provide a clean summary of the candidate details (name, graduation, skills, certifications) in a structured format. If no, just say 'You are not matched'.\n\nResume: {sample_resume}"
    await run_single_query(match_query)

    # Query 3: Preferred role & improvements (unchanged)
    await run_single_query("What was my preferred role? Can you suggest improvements?")

    # Verify persistence and state
    try:
        session = await session_service.get_session(
            app_name=APP_NAME, user_id=USER_ID, session_id="resume_screening_session_02"
        )
        print("Session State:", session.state)

        # Check compaction
        # This section checks for compaction, but compaction is now explicitly disabled above.
        # If re-enabling compaction, ensure the event object's structure matches expected types.Event
        for event in session.events:
            if hasattr(event, 'actions') and event.actions and hasattr(event.actions, 'compaction') and event.actions.compaction:
                print("Compaction Summary:", event.actions.compaction['compacted_content']['parts'][0]['text'])
                break
    except Exception as e:
        print(f"Error verifying session: {e}")

# Run the demo
await demo_resume_screener()
