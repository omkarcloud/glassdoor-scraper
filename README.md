# 🏢 Glassdoor Scraper

Glassdoor Scraper is a **free and open-source** scraper that gets you **unlimited** detailed Glassdoor data for free.

## ✨ What Can I Get?

- ⭐ **Reviews on 1M+ companies** — pros, cons, star ratings, job title, location & CEO approval
- 💰 **191K+ salaries at Google alone** — base, bonus & total pay percentiles by title and city
- 🎤 **26K+ Google interview reviews alone** — questions asked, difficulty, process & offer outcome
- 💼 **269K+ live engineering jobs** — salary ranges, Easy Apply & 17 search filters

## 🎥 Example: A Full Glassdoor Review

```json
{
  "count": 49089,
  "current_page": 1,
  "total_pages": 4909,
  "company": {
    "id": 9079,
    "name": "Google",
    "link": "https://www.glassdoor.com/Overview/Working-at-Google-EI_IE9079.11,17.htm",
    "logo": "https://media.glassdoor.com/sql/9079/google-squarelogo-1441130773284.png"
  },
  "reviews_count": 71220,
  "reviews": [
    {
      "id": 2757802,
      "link": "https://www.glassdoor.com/Reviews/Employee-Review-Google-E9079-RVW2757802.htm",
      "title": "Moving at the speed of light, burn out is inevitable",
      "pros": "1) Food, food, food. 15+ cafes on main campus (MTV) alone. Mini-kitchens, snacks, drinks, free breakfast/lunch/dinner, all day, errr'day...",
      "cons": "1) Work/life balance. What balance? All those perks and benefits are an illusion...",
      "advice_to_management": "1) Don't dismiss emotional intelligence and adaptive leadership...",
      "rating": 4.0,
      "date": "2013-06-21",
      "job_title": "Program Manager",
      "location": { "id": "IC1147431", "name": "Mountain View, CA", "type": "city" },
      "is_current_employee": false,
      "years_employed": 9,
      "sub_ratings": { "career_opportunities": 3.0, "compensation_and_benefits": 5.0, "culture_and_values": 3.0, "senior_management": 3.0, "work_life_balance": 2.0 },
      "recommends_company": false,
      "ceo_opinion": "no_opinion",
      "business_outlook": "negative",
      "helpful_count": 3878
    }
  ]
}
```

*Trimmed for readability.*

## 🚀 Unlimited Free Glassdoor Data — Get It in 60 Seconds

1️⃣ Clone and install:
```bash
git clone https://github.com/omkarcloud/glassdoor-scraper
cd glassdoor-scraper
python -m pip install -r requirements.txt
```

2️⃣ Start the API:
```bash
python run.py
```

3️⃣ Get your first data:
```bash
curl "http://localhost:8000/companies/reviews?company=Google&sort=popular"
```

```json
{
  "count": 49089,
  "per_page": 10,
  "current_page": 1,
  "total_pages": 4909,
  "next": "http://localhost:8000/companies/reviews?company=Google&sort=popular&page=2",
  "company": { "id": 9079, "name": "Google" },
  "reviews_count": 71220,
  "reviews": [
    {
      "id": 2757802,
      "title": "Moving at the speed of light, burn out is inevitable",
      "rating": 4.0,
      "date": "2013-06-21",
      "job_title": "Program Manager",
      "location": { "id": "IC1147431", "name": "Mountain View, CA", "type": "city" },
      "years_employed": 9,
      "recommends_company": false,
      "business_outlook": "negative",
      "helpful_count": 3878
    }
  ]
}
```

All 25 endpoints are now live at `http://localhost:8000`.

## 📚 Endpoints

25 endpoints cover everything you need.

| Endpoint | Path | Returns |
|---|---|---|
| Company Reviews | `/companies/reviews` | Employee reviews with pros, cons, ratings, job title and location |
| Company Details | `/companies/details` | Full profile: CEO, ratings, size, revenue, awards, competitors |
| Company Salaries | `/companies/salaries` | Pay by job title with base, bonus and total percentiles |
| Company Interviews | `/companies/interviews` | Interview questions, process, difficulty and offer outcome |
| Company Ratings | `/companies/ratings` | Category ratings, star distribution and industry benchmark |
| Company Benefits | `/companies/benefits` | Employee-rated health, 401K, parental leave and PTO benefits |
| Compare Companies | `/companies/compare` | 2–5 companies side by side, salaries included |
| Company Jobs | `/companies/jobs` | A company's open jobs with salary estimates |
| Company Photos / Locations | `/companies/photos`, `/companies/locations` | Office photos and every office address |
| Company Community Posts | `/companies/community-posts` | What employees say about a company in the Community |
| Company Autocomplete / Search Companies | `/companies/autocomplete`, `/companies/search` | Find any of 1M+ companies by name, city or rating |
| Search Jobs / Job Details | `/jobs/search`, `/jobs/details` | 30 jobs per page with 17 filters, then the full posting |
| Salary Estimate / Salaries by Company | `/salaries/estimate`, `/salaries/by-company` | Market pay for any job title, and who pays most |
| Job Title / Location Autocomplete | `/job-titles/autocomplete`, `/locations/autocomplete` | Titles and places with the IDs every filter accepts |
| Industries | `/industries` | Every sector, industry and job function with its ID |
| Bowl Details / Related Bowls / Bowl Posts | `/community/bowls/details`, `/community/bowls/related`, `/community/bowls/posts` | Glassdoor Community groups and their hottest posts |
| Post Details / Post Comments | `/community/posts/details`, `/community/posts/comments` | One post with its full comment threads |


## 🔍 Exploring Parameters

The same API is published on RapidAPI, and its playground is the easiest place to try parameters and see raw responses. Once a request looks right, run it locally for **unlimited free** data.

1. [Subscribe to the free plan](https://rapidapi.com/OmkarCloud/api/best-glassdoor-scraper-free-1000-calls/pricing) — 1,000 calls/month, no credit card.
2. [Try the endpoints in the playground](https://rapidapi.com/OmkarCloud/api/best-glassdoor-scraper-free-1000-calls/playground) — every param is pre-filled, so you see real data in one click.
3. Copy the generated code and replace `https://best-glassdoor-scraper-free-1000-calls.p.rapidapi.com` with `http://localhost:8000`. It will now run against your local API.

```python
import requests

# generated by the playground, host swapped for the local API
response = requests.get(
    "http://localhost:8000/companies/reviews",
    params={"company": "Google"},
)
print(response.json())
```

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about Glassdoor Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://api.whatsapp.com/send?phone=918178804274&text=I%20need%20help%20using%20the%20Glassdoor%20Scraper%20API.)

[![Ask Us by Email about Glassdoor Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Help%20with%20Glassdoor%20Scraper%20API&body=I%20need%20help%20using%20the%20Glassdoor%20Scraper%20API.)

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — type "dentists in New York", get every business as a ready-to-call lead list: phones, emails, websites & reviews. Up to 100K free leads/month.
- [**G2 Scraper**](https://www.omkar.cloud/tools/g2-scraper) — G2 product details, ratings & AI-found contacts
- [**Website Email Contact Scraper**](https://www.omkar.cloud/tools/website-email-contact-scraper) — emails, phones & socials from any website
- [**AliExpress Scraper**](https://www.omkar.cloud/tools/aliexpress-scraper) — live product details, SKU variants, stock & shipping
- [**Booking Scraper**](https://www.omkar.cloud/tools/booking-scraper) — Booking.com hotels: prices, ratings, rooms & amenities
- [**IMDb Scraper**](https://github.com/omkarcloud/imdb-scraper) — movies, TV shows, ratings, cast & box office

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/glassdoor-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/glassdoor-scraper)
