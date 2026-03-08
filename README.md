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
