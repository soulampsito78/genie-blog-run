# genie-blog-run

Automated publishing system for the Genie persona briefing content.

This project generates and distributes two daily briefings based on a single character persona.

Modes

1. today_genie
06:30 pre-market briefing
Role: financial news anchor

2. tomorrow_genie
15:00 next-day weather & life briefing
Role: weather/lifestyle broadcast caster


--------------------------------
SYSTEM PURPOSE
--------------------------------

The system automates the following pipeline:

Generate → Validate → Asset Process → Deliver → Draft/Publish

Automation is intentionally conservative.
Publishing safety is prioritized over speed.


--------------------------------
ARCHITECTURE OVERVIEW
--------------------------------

Cloud Scheduler
↓
Cloud Run
↓
FastAPI
↓
mode router
↓
runtime_input
↓
build_full_prompt()
↓
Gemini generation
↓
JSON validation
↓
delivery / publishing pipeline


--------------------------------
PROJECT DOCUMENT AUTHORITY
--------------------------------

When conflicts occur between documents:

1 GENIE_PROJECT_SSOT_v2
2 GENIE_CONTENT_AND_OUTPUT_CONTRACT_v2
3 GENIE_CONTENT_POLICY_AND_OUTPUT_SPEC_v2
4 GENIE_SYSTEM_AND_API_ARCHITECTURE_v2
5 GENIE_DELIVERY_AND_PUBLISHING_OPS_v2
6 GENIE_OPS_AND_MAINTENANCE_SYSTEM_v2


Older v1 documents are reference only.


--------------------------------
OFFICIAL SYSTEM STATES
--------------------------------

generated
validated
assets_ready
emailed
review_required
drafted
published
failed

review_required is not a failure state.


--------------------------------
MODE POLICY
--------------------------------

today_genie

Financial briefing mode.

Strict hallucination prevention rules apply.

The system must never fabricate:

market index numbers  
interest rates  
exchange rates  
earnings  
analyst opinions  
news headlines

If critical input data is missing,
generation must be shortened or aborted.



tomorrow_genie

Next-day preparation briefing.

Primary data source:

weather forecast for tomorrow (reference time 06:00).

No precise weather numbers may be invented.



--------------------------------
PLAYWRIGHT POLICY
--------------------------------

Naver Blog posting uses Playwright browser automation.

However Playwright is treated as a **limited auxiliary automation layer**.

Default workflow:

Generate
↓
Validate
↓
Draft save
↓
Human review
↓
Publish

today_genie

automatic publish NOT allowed


tomorrow_genie

draft-first model
auto publish may be introduced later


--------------------------------
OUTPUT CONTRACT
--------------------------------

The AI must return:

A single JSON object only.

No markdown
No explanation
No extra text

Channels must be separated:

web_html
email_html
naver_blog_body


--------------------------------
REPOSITORY STRUCTURE
--------------------------------

main.py
FastAPI runtime entry

prompts.py
Prompt architecture and system prompts

future services

market_data_service
weather_data_service
email_delivery_service
naver_blog_poster


--------------------------------
CURRENT DEVELOPMENT PRIORITIES
--------------------------------

1 Prevent hallucination in today_genie
2 Integrate real market data input
3 Integrate weather data input
4 Channel-separated outputs
5 Draft-based publishing pipeline


--------------------------------
RUNTIME ENVIRONMENT
--------------------------------

Core environment variables:

- PROJECT_ID  
  Google Cloud project ID used for Vertex AI initialization.

- VERTEX_LOCATION  
  Vertex AI location/region (default: "global").

- VERTEX_MODEL  
  Vertex AI Gemini model name (default: "gemini-2.5-flash").

- OPENWEATHER_API_KEY  
  OpenWeather API key used to fetch the 5-day/3-hour forecast for
  tomorrow_genie weather_context. If this is not set, weather_context
  is left empty and tomorrow_genie degrades to a draft_only /
  review_required path instead of fabricating weather data.

- TODAY_GENIE_OVERNIGHT_US_MARKET_JSON  
  JSON string containing pre-fetched overnight US market context for
  today_genie. If unset or invalid, overnight_us_market is treated as
  missing and validation falls back to a draft_only / review_required
  path rather than fabricating numbers.

- TODAY_GENIE_MACRO_INDICATORS_JSON  
  JSON string containing pre-fetched macro indicators for today_genie
  (e.g., rates, key indices, macro data summaries). If unset or invalid,
  macro_indicators is treated as missing.

- TODAY_GENIE_TOP_MARKET_NEWS_JSON  
  JSON string containing an array of top market news items for
  today_genie. If unset or invalid, top_market_news is treated as
  missing.

- TODAY_GENIE_RISK_FACTORS_JSON  
  JSON string containing an array of key risk factors for today_genie.
  If unset or invalid, risk_factors is treated as missing.


--------------------------------
ORCHESTRATOR & EMAIL DELIVERY
--------------------------------

Used when running the orchestrator (e.g. run_genie_job + send_email_if_allowed):

- GENIE_API_URL  
  Base URL of the Genie API (default: http://localhost:8080).

- GENIE_REQUEST_TIMEOUT  
  Timeout in seconds for the API request (default: 120).

- GENIE_API_RETRIES  
  Number of retries for transient API failures (default: 2).

- GENIE_API_RETRY_DELAY_SEC  
  Delay in seconds between retries (default: 2.0).

Email delivery (email_sender.py, invoked only when policy allows):

- SMTP_HOST  
  SMTP server host (e.g. smtp.gmail.com, smtp.sendgrid.net).

- SMTP_PORT  
  SMTP port (default: 587).

- SMTP_USER  
  SMTP username / login.

- SMTP_PASSWORD or SMTP_APP_PASSWORD  
  SMTP password or app password.

- EMAIL_FROM  
  From address (defaults to SMTP_USER if unset).

- EMAIL_TO  
  Comma-separated list of recipient addresses.

Naver Blog draft (naver_draft.py, Playwright; invoked only when policy allows):

- NAVER_ID  
  Naver account ID (login).

- NAVER_PASSWORD or NAVER_APP_PASSWORD  
  Naver account password or app password.

- NAVER_BLOG_ID  
  Blog identifier (used in blog.naver.com/{NAVER_BLOG_ID}/postwrite).

- NAVER_HEADLESS  
  Set to "true" (default) to run browser headless.

- NAVER_DRAFT_TIMEOUT_MS  
  Timeout for draft flow in milliseconds (default: 60000).

Note: Playwright requires Chromium to be installed (e.g. `playwright install chromium`). The Genie API Dockerfile does not install browsers; use a separate worker image or install step for the orchestrator when using Naver draft.

Secret Manager (production): For SMTP and Naver credentials, you can mount secrets as files and set SMTP_PASSWORD_FILE, NAVER_PASSWORD_FILE (etc.) to the mount path; the code reads from the file when the env var is set. See OPERATIONS.md. For first production rollout (secrets, scheduler, worker, first-run checklist), see ROLLOUT.md.

