# OSU P-card Audit Explorer (Part IV)

Two-tab Streamlit website for the Analytics Mindset P-card assignment:

1. **Ask Questions**: Natural-language audit questions with built-in question templates. Optional OpenAI API support for broader text-to-SQL questions.
2. **Prohibited Purchases Dashboard**: Select a year; search **Description** or **Vendor** independently; view and export transaction results.

The included `osu_pcards.db.zip` contains only Oklahoma State University rows from the instructor-supplied dataset (2010–2014). The project does not rely on the public state database. All search matches are **potential** exceptions, not proven violations.

## Run locally on a Mac

Install Python 3.10+ and VS Code if needed. In Terminal, open this project folder and run:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

The database archive is extracted automatically when the app first starts. The site should open at `http://localhost:8501`. Stop it with `Control + C` in Terminal.

## Optional natural-language AI support

Built-in questions work without an API key. For broader questions, set a server-side `OPENAI_API_KEY` using Streamlit secrets. Create `.streamlit/secrets.toml` locally (never commit it):

```toml
OPENAI_API_KEY = "your-api-key-here"
```

The AI option uses OpenAI's API and may incur usage charges. Generated SQL is displayed for review and is executed in SQLite read-only mode with a short timeout. Do not upload a key to GitHub or enter it into the website's public fields. The API-based feature requires an active API key and internet access; the built-in question templates do not.

## Deploy on GitHub and Streamlit Community Cloud

1. Create a new **private** GitHub repository for the assignment (if Streamlit deployment settings support it) or use a public repository if required by your course. The dataset is included with the project, so confirm your course's data-sharing rules before making it public.
2. Upload `app.py`, `requirements.txt`, `README.md`, `.gitignore`, and `osu_pcards.db.zip` to the repository. Do not upload `.venv`, `.env`, or `.streamlit/secrets.toml`.
3. Visit https://share.streamlit.io and sign in with GitHub. Select **Create app**, choose the repository, branch `main`, and entrypoint `app.py`.
4. If using the optional AI feature, set `OPENAI_API_KEY` in the app's **Secrets** settings. Do not commit it to GitHub.
5. Deploy, open the public app URL, and test both tabs. Submit that URL and your repository URL with the completed Parts II–III document.

**Size note:** GitHub rejects individual files of 100 MiB or more. This project's compressed OSU-only database stays below that limit; verify its size before uploading. Streamlit Community Cloud resource limits and GitHub integration requirements can change.

## Limitations and controls

- Keyword matching is not a definitive policy-violation determination. Some categories, such as personal purchases, cannot be reliably determined from description/vendor alone.
- Searches return at most 5,000 rows for responsiveness; downloaded CSV includes only the displayed rows.
- Built-in questions cover common spending and transaction queries; AI support is optional.
- AI-generated SQL should be reviewed. The application only executes read-only queries and has an execution time limit.
- Database records are teaching-case data and should not be used to allege wrongdoing.
