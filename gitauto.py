import asyncio
import json
import os
import sys
import time
import google.generativeai as genai
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# ==========================================
# CONFIGURATION
# ==========================================
REPO_OWNER = "shubhamrd"
REPO_NAME = "electro-sample"
ISSUE_NUMBER = 2
FILE_TO_UPDATE = "index.html" 
BASE_BRANCH = "main"
# ==========================================

def safe_parse_json(text):
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return None

async def run_workflow():
    github_token = os.environ.get("GITHUB_PERSONAL_ACCESS_TOKEN")
    gemini_key = os.environ.get("GEMINI_API_KEY")
    
    if not github_token or not gemini_key:
        print("❌ ERROR: Ensure both GITHUB_PERSONAL_ACCESS_TOKEN and GEMINI_API_KEY are set.")
        return

    genai.configure(api_key=gemini_key)

    server_params = StdioServerParameters(
        command="docker",
        args=[
            "run", "-i", "--rm",
            "-e", "GITHUB_PERSONAL_ACCESS_TOKEN", 
            "ghcr.io/github/github-mcp-server"
        ],
        env={"GITHUB_PERSONAL_ACCESS_TOKEN": github_token}
    )

    print("🚀 Initializing headless MCP connection to GitHub...")
    
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            
            cmd_get_issue = "issue_read"
            cmd_get_file = "get_file_contents"
            cmd_create_branch = "create_branch"
            cmd_push_files = "push_files"  # Using the superior push tool
            cmd_create_pr = "create_pull_request"

            unique_id = int(time.time())
            branch_name = f"fix-ui-perf-{ISSUE_NUMBER}-{unique_id}"

            try:
                # --- STEP 1: Read the Issue ---
                print(f"📖 Fetching details for issue #{ISSUE_NUMBER}...")
                issue_response = await session.call_tool(cmd_get_issue, {
                    "owner": REPO_OWNER, 
                    "repo": REPO_NAME, 
                    "issue_number": ISSUE_NUMBER
                })
                raw_issue = issue_response.content[0].text
                issue_data = safe_parse_json(raw_issue)
                issue_text = issue_data.get('body', raw_issue) if isinstance(issue_data, dict) else raw_issue

                # --- STEP 2: Get the Current File Content ---
                print(f"🔍 Fetching current file content for '{FILE_TO_UPDATE}'...")
                current_file_content = ""
                
                try:
                    file_response = await session.call_tool(cmd_get_file, {
                        "owner": REPO_OWNER,
                        "repo": REPO_NAME,
                        "path": FILE_TO_UPDATE,
                        "branch": BASE_BRANCH
                    })
                    # The server returns raw HTML text directly for this tool
                    current_file_content = file_response.content[0].text
                    print("   ✅ File found and content extracted successfully.")
                except Exception as e:
                    print(f"   ⚠️ File could not be read. AI will generate it from scratch. (Error: {e})")

                # --- STEP 3: Generate the Code Fix Using Gemini ---
                print("🧠 Sending issue and code to Gemini to generate UI improvements...")
                ai_prompt = f"""
                You are an expert web developer specializing in UI and frontend performance optimization.
                Fix this issue: {issue_text}
                
                Current code for {FILE_TO_UPDATE}:
                ```html
                {current_file_content}
                ```
                
                Return ONLY the fully updated, optimized code. Do not include markdown formatting blocks, no explanations, just raw code.
                """
                model = genai.GenerativeModel('gemini-3.5-flash')
                ai_response = await model.generate_content_async(ai_prompt)
                new_code = ai_response.text.strip()
                
                if new_code.startswith("```"):
                    lines = new_code.split("\n")
                    if len(lines) >= 2:
                        new_code = "\n".join(lines[1:-1])
                        
                # Force a tiny difference so GitHub guarantees it sees a change
                new_code += f"\n<!-- AI Run ID: {unique_id} -->\n"

                print(f"   ✅ AI generated {len(new_code)} characters of optimized code.")

                # --- STEP 4: Create a New Branch ---
                print(f"🌿 Creating unique branch '{branch_name}'...")
                await session.call_tool(cmd_create_branch, {
                    "owner": REPO_OWNER,
                    "repo": REPO_NAME,
                    "branch": branch_name
                })

                # --- STEP 5: Push Files (Handles SHAs automatically!) ---
                print(f"💾 Committing code to '{branch_name}'...")
                push_response = await session.call_tool(cmd_push_files, {
                    "owner": REPO_OWNER,
                    "repo": REPO_NAME,
                    "branch": branch_name,
                    "message": f"Optimize UI performance (Issue #{ISSUE_NUMBER})",
                    "files": [
                        {
                            "path": FILE_TO_UPDATE,
                            "content": new_code
                        }
                    ]
                })
                
                push_result_text = push_response.content[0].text
                
                # Check if the push failed before continuing
                if "error" in push_result_text.lower() or "failed" in push_result_text.lower():
                    print(f"   ❌ Commit failed! GitHub API responded with: {push_result_text}")
                    return
                else:
                    print("   ✅ Code committed successfully.")

                # --- STEP 6: Create the Pull Request ---
                print("📤 Creating Pull Request...")
                pr_response = await session.call_tool(cmd_create_pr, {
                    "owner": REPO_OWNER,
                    "repo": REPO_NAME,
                    "title": f"UI Performance Optimization for Issue #{ISSUE_NUMBER}",
                    "body": f"This PR was generated automatically via Gemini to resolve #{ISSUE_NUMBER}.",
                    "head": branch_name,
                    "base": BASE_BRANCH
                })
                
                raw_pr = pr_response.content[0].text
                pr_data = safe_parse_json(raw_pr)
                
                if pr_data and isinstance(pr_data, dict):
                    pr_url = pr_data.get("html_url", "URL not found")
                else:
                    pr_url = raw_pr.split('\n')[0][:100]
                
                print("\n🎉 Workflow complete!")
                print(f"👉 Pull Request Details: {pr_url}")

            except Exception as inner_e:
                print(f"\n❌ SCRIPT CRASHED AT RUNTIME: {inner_e}")

if __name__ == "__main__":
    asyncio.run(run_workflow())