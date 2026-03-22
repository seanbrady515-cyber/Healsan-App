from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import anthropic
import base64
import os

app = Flask(__name__, static_folder="static")
CORS(app)

client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

SYSTEM_PROMPTS = {
    "cv": """You are an expert immigration document specialist working on US NIW and EB-1A visa applications.
Draft a comprehensive, well-structured academic and professional CV.
Sections to include: Education, Professional Experience, Research Interests, Publications (with citations), Awards & Honours, Professional Memberships, Conference Presentations.
Use precise, formal language. Highlight research impact, citation counts, h-index if available.""",

    "rs": """You are an expert immigration document specialist drafting a Research Statement for a US NIW or EB-1A visa petition.
Structure the document with clearly numbered and titled Contributions. For each contribution:
- Describe the research and methodology
- Explain the significance and novelty
- Quantify impact (citations, adoption, awards)
- Connect to broader national or scientific benefit
Use formal academic language appropriate for USCIS adjudicators who are not domain experts.""",

    "rp": """You are an expert immigration document specialist drafting a Research Plan for a US NIW or EB-1A visa petition.
Structure: (1) Overview of proposed US-based research, (2) Specific aims and milestones, (3) National interest and benefit, (4) Why this client is uniquely positioned to execute this work.
Use forward-looking, persuasive language. Quantify expected impact where possible.""",

    "cit": """You are an expert immigration document specialist. Your task: document notable independent citations of the client's academic work.
For each citation: (1) Full citation of the citing paper, (2) Journal name and impact factor if known, (3) The exact context in which the citing author relied upon or praised the client's work, (4) Why this citation is significant.
Write in a formal style suitable for an NIW or EB-1A immigration petition exhibit.""",

    "rec": """You are an expert immigration document specialist drafting a Recommendation Letter for a US NIW or EB-1A visa petition.
Structure: (1) Recommender's credentials and relationship to client, (2) Overview of client's work the recommender knows, (3) Specific praise and examples of extraordinary ability, (4) Statement that client's work is of national interest, (5) Strong closing endorsement.
Write in the voice of a distinguished expert. Tone: formal, authoritative, and compelling.""",

    "pet": """You are an expert immigration document specialist drafting a Petition Letter for a US NIW or EB-1A visa application submitted to USCIS.
Structure: (1) Introduction and visa category, (2) Client's field and its national importance, (3) Client's extraordinary achievements and recognition, (4) Evidence meeting the legal standard (NIW: Dhanasar three-prong test; EB-1A: extraordinary ability criteria), (5) Conclusion and request.
Be persuasive, precise, and legally aware. Reference relevant USCIS precedent decisions where appropriate."""
}


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/draft", methods=["POST"])
def draft():
    try:
        section = request.form.get("section", "cv")
        command = request.form.get("command", "")
        cv_context = request.form.get("cv_context", "")
        memories = request.form.get("memories", "")
        contrib = request.form.get("contrib", "")
        previous_draft = request.form.get("previous_draft", "")
        feedback = request.form.get("feedback", "")

        content_parts = []

        # Add CV context
        if cv_context and section != "cv":
            content_parts.append({
                "type": "text",
                "text": f"CLIENT CV CONTEXT:\n{cv_context}\n\n---\n"
            })

        # Add uploaded files
        files = request.files.getlist("files")
        for f in files:
            data = f.read()
            b64 = base64.standard_b64encode(data).decode("utf-8")
            mime = f.content_type or "application/pdf"
            if "pdf" in mime:
                content_parts.append({
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": b64
                    }
                })
            else:
                try:
                    text = data.decode("utf-8", errors="replace")
                    content_parts.append({
                        "type": "text",
                        "text": f"[File: {f.filename}]\n{text}"
                    })
                except Exception:
                    content_parts.append({
                        "type": "text",
                        "text": f"[File: {f.filename} — could not read content]"
                    })

        # Contribution assignments
        if contrib and section == "rs":
            content_parts.append({
                "type": "text",
                "text": f"CONTRIBUTION ASSIGNMENTS:\n{contrib}\n"
            })

        # Feedback revision mode
        if feedback and previous_draft:
            content_parts.append({
                "type": "text",
                "text": f"PREVIOUS DRAFT:\n\n{previous_draft}\n\n---\nFEEDBACK: {feedback}\n\nPlease revise accordingly."
            })
        else:
            default_cmds = {
                "cv": "Build a comprehensive CV from the uploaded materials.",
                "rs": "Draft the Research Statement using the contribution assignments above.",
                "rp": "Draft the Research Plan.",
                "cit": "Draft the Notable Citations section from the uploaded papers.",
                "rec": "Draft the Recommendation Letter.",
                "pet": "Draft the Petition Letter."
            }
            content_parts.append({
                "type": "text",
                "text": command or default_cmds.get(section, "Draft the document.")
            })

        # Build system prompt with memories
        sys_prompt = SYSTEM_PROMPTS.get(section, SYSTEM_PROMPTS["cv"])
        if memories:
            sys_prompt += f"\n\nLEARNED PREFERENCES FROM PREVIOUS FEEDBACK:\n{memories}"
        if feedback and previous_draft:
            sys_prompt += "\nYou are revising a previously drafted document. Apply the feedback carefully and return only the revised document."

        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=4096,
            system=sys_prompt,
            messages=[{"role": "user", "content": content_parts}]
        )

        text = "".join(b.text for b in response.content if hasattr(b, "text"))
        return jsonify({"result": text})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/search", methods=["POST"])
def search():
    try:
        data = request.get_json()
        query = data.get("query", "")
        cv_context = data.get("cv_context", "")
        memories = data.get("memories", "")

        sys_prompt = SYSTEM_PROMPTS["cit"]
        if memories:
            sys_prompt += f"\n\nLEARNED PREFERENCES:\n{memories}"

        cv_text = f"CLIENT CV:\n{cv_context}\n\n" if cv_context else ""

        response = client.messages.create(
            model="claude-opus-4-6",
            max_tokens=4096,
            system=sys_prompt,
            messages=[{
                "role": "user",
                "content": f"{cv_text}Please search the web for: {query}\n\nFind papers that cite this client's work, then draft the Notable Citations section."
            }],
            tools=[{"type": "web_search_20250305", "name": "web_search"}]
        )

        text = "".join(b.text for b in response.content if hasattr(b, "text"))
        return jsonify({"result": text})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


port = int(os.environ.get("PORT", 10000))
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=port)
