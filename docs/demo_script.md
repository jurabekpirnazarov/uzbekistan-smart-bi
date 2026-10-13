# 5-minute demo script

Story: *"I have 700 million UZS and want to open a bakery in Fergana region."*

Before the demo: `python manage.py dev`, open http://localhost:5174, close other tabs.

| Time | Step | What to say |
|---|---|---|
| 0:00 | **Home.** Point at the KPI strip and the 3D map preview. | "All numbers are official SIAT statistics for 14 regions and 208 districts and cities, loaded automatically." |
| 0:30 | Type the story into **Ask AI** (or click the first example chip). | "The AI analyst works in English, Uzbek and Russian." |
| 0:45 | Watch the tool chips ("Scoring locations"). | "The AI never calculates numbers. It calls tools: here, the Business Opportunity Score model." |
| 1:15 | Read the answer: Official statistics / Model prediction / AI interpretation / Sources. Point at **"✓ N numbers verified"**. | "Statistics, model output and interpretation are separate. Every number in the answer was checked against the tool results." |
| 1:45 | Click **Show on map**. | "The top 5 districts are highlighted on the 3D map. Height and colour show rank." |
| 2:15 | Click Fergana city → **Score businesses here** → the **Recommend** page. Open the first result. | "Here is the full breakdown: official value, year, normalised score, weight and contribution, with a SIAT link per factor. Contributions add up to the score." |
| 3:00 | Point at the **rank range** and switch the goal to *Low competition*. | "Rank ranges show how much a result depends on the weights; changing the goal re-weights the model." |
| 3:30 | **Forecast** page: population of Fergana city. | "Forecasts are backtested. The dashed line and the 80 % / 95 % bands are model predictions, never statistics." |
| 4:00 | **Monitoring** page. | "We monitor data freshness, quality checks, forecast error, drift (for example the 2026 business-count break), and every AI run: latency, cost, unverified numbers." |
| 4:30 | Ask "What is the average wage in Chilanzar district?" | "When official data is missing the AI says so instead of inventing a number." |
| 4:50 | Close with the disclaimer. | "The score is decision support, not a guarantee." |

Backup if the internet is down: the rule-based agent (no OpenAI key) answers the same questions, and the
map still renders without the basemap.
