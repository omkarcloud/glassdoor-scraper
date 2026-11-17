"""Value helpers for the Glassdoor parsers: numbers, text, dates. Pure
functions that tolerate None and junk. Same behaviour as
similarweb/shared.py's helpers of the same name, kept local or taken from
scraper_utils (the glassdoor package is published as its own repo and cannot
import another site)."""
from scraper_utils.text import clean as text
from scraper_utils.values import num, rounded, to_int_round as to_int
from scraper_utils.dates import iso_day as iso_date
