"""Marshmallow request schemas for every /glassdoor/* route.

Generic fields live in the shared top-level schema_fields.py; this module
adds the Glassdoor resolvers (refs.py). Every schema's load() output is the
kwargs dict its endpoint function takes.

ONE param per input (tripadvisor QueryOrIdField convention, never a sibling
`url` / `id` pair): `company` takes an employer id, ANY Glassdoor company
link or a company name; `job` a listing id or job link; `location` a place
name, a Glassdoor location id (IC1132348) or a search link; `country` an ISO
code or name; `industry` a sector / industry id or name; `job_function` an
id or name; `bowl` / `post` a Community handle, id or link.
"""
from marshmallow import ValidationError, fields, validate, validates_schema

from glassdoor import community, companies, jobs, reference, refs, salaries
from schema_fields import (BaseSchema, ChoiceField, CommaListField, Flag, PageField, PositiveInt,
                           QueryField, RefField, StrippedString)


# ---- resolver fields ------------------------------------------------------------------------

class _OptionalRef(RefField):
    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("load_default", None)
        super().__init__(**kwargs)


class CompanyField(RefField):
    resolver = staticmethod(refs.resolve_company)


class OptionalCompanyField(_OptionalRef):
    resolver = staticmethod(refs.resolve_company)


class JobField(RefField):
    resolver = staticmethod(refs.resolve_job)


class LocationField(_OptionalRef):
    resolver = staticmethod(refs.resolve_location)


class CountryField(_OptionalRef):
    resolver = staticmethod(refs.resolve_country)


class IndustryField(_OptionalRef):
    resolver = staticmethod(refs.resolve_industry)


class JobFunctionField(_OptionalRef):
    resolver = staticmethod(refs.resolve_job_function)


class BowlField(RefField):
    resolver = staticmethod(refs.resolve_bowl)


class PostField(RefField):
    resolver = staticmethod(refs.resolve_post)


class CompaniesField(fields.Field):
    """'9079, Microsoft, https://…-E1138.htm' -> [9079, {"name": "Microsoft"}, 1138]."""

    def _deserialize(self, value, attr, data, **kwargs):
        try:
            return refs.resolve_companies(str(value or ""))
        except ValueError as e:
            raise ValidationError(str(e))


def _title(required=False):
    if required:
        return QueryField(max_length=120)
    return StrippedString(required=False, load_default=None, validate=validate.Length(min=1, max=120))


# ---- companies ------------------------------------------------------------------------------------

class AutocompleteSchema(BaseSchema):
    query = QueryField(max_length=100)


class CompanySearchSchema(BaseSchema):
    query = StrippedString(required=False, load_default=None, validate=validate.Length(max=100))
    location = LocationField()
    job_title = _title()
    min_rating = fields.Float(load_default=None, validate=validate.Range(min=1, max=5))
    page = PageField(max_page=100)


class CompanySchema(BaseSchema):
    company = CompanyField()


EMPLOYMENT_STATUSES = ["regular", "part_time", "contract", "intern", "freelance"]


class CompanyReviewsSchema(BaseSchema):
    company = CompanyField()
    sort = ChoiceField(list(companies.REVIEW_SORTS), load_default="most_recent")
    rating = fields.Integer(load_default=None, strict=False, validate=validate.Range(min=1, max=5))
    job_title = _title()
    location = LocationField()
    employment_status = CommaListField(allowed=EMPLOYMENT_STATUSES, upper=False, max_items=5)
    current_employees_only = Flag()
    query = StrippedString(required=False, load_default=None, validate=validate.Length(min=2, max=100))
    page = PageField(max_page=1000)


class CompanyRatingsSchema(BaseSchema):
    company = CompanyField()
    job_title = _title()
    location = LocationField()
    employment_status = CommaListField(allowed=EMPLOYMENT_STATUSES, upper=False, max_items=5)


class CompanyInterviewsSchema(BaseSchema):
    company = CompanyField()
    sort = ChoiceField(list(companies.INTERVIEW_SORTS), load_default="most_recent")
    job_title = _title()
    location = LocationField()
    outcome = CommaListField(value_map={"accepted_offer": "ACCEPT_OFFER", "declined_offer": "DECLINE_OFFER",
                                        "no_offer": "NO_OFFER"}, max_items=3)
    experience = CommaListField(allowed=["positive", "neutral", "negative"], upper=False, max_items=3)
    page = PageField(max_page=1000)


class CompanySalariesSchema(BaseSchema):
    company = CompanyField()
    job_title = _title()
    location = LocationField()
    pay_period = ChoiceField(["annual", "monthly", "hourly"])
    sort = ChoiceField(list(companies.SALARY_SORTS), load_default="popular")
    page = PageField(max_page=500)


class CompanyBenefitsSchema(BaseSchema):
    company = CompanyField()
    country = CountryField(load_default=1)


class CompanyPhotosSchema(BaseSchema):
    company = CompanyField()
    page = PageField(max_page=100)


class CompanyJobsSchema(BaseSchema):
    company = CompanyField()
    query = StrippedString(required=False, load_default=None, validate=validate.Length(max=100))
    location = LocationField()
    date_posted = ChoiceField(list(jobs.DATE_POSTED), load_default="any")
    job_function = JobFunctionField()
    sort = ChoiceField(["relevant", "most_recent"], load_default="relevant")
    page = PageField(max_page=30)


class CompanyCompareSchema(BaseSchema):
    companies = CompaniesField(required=True)
    job_title = _title()


class CompanyCommunitySchema(BaseSchema):
    company = CompanyField()
    limit = fields.Integer(load_default=20, strict=False, validate=validate.Range(min=1, max=50))


# ---- salaries --------------------------------------------------------------------------------------

class SalaryEstimateSchema(BaseSchema):
    job_title = _title(required=True)
    location = LocationField()
    years_of_experience = ChoiceField(list(salaries.EXPERIENCE), load_default="all")
    industry = IndustryField()


class SalaryByCompanySchema(BaseSchema):
    job_title = _title(required=True)
    location = LocationField()
    page = PageField(max_page=100)


class SalaryReportsSchema(BaseSchema):
    job_title = _title(required=True)
    company = OptionalCompanyField()
    location = LocationField()
    pay_period = ChoiceField(["annual", "monthly", "hourly"], load_default="annual")
    years_of_experience = ChoiceField(list(salaries.EXPERIENCE), load_default="all")
    page = PageField(max_page=100)


# ---- jobs ------------------------------------------------------------------------------------------

class JobSearchSchema(BaseSchema):
    query = StrippedString(required=False, load_default=None, validate=validate.Length(max=100))
    location = LocationField()
    radius = fields.Integer(load_default=None, strict=False, validate=validate.OneOf([0, 5, 10, 15, 25, 50, 100]))
    date_posted = ChoiceField(list(jobs.DATE_POSTED), load_default="any")
    easy_apply_only = Flag()
    remote_only = Flag()
    job_type = ChoiceField(list(jobs.JOB_TYPES))
    seniority = ChoiceField(list(jobs.SENIORITY))
    min_salary = PositiveInt(max_value=10_000_000)
    max_salary = PositiveInt(max_value=10_000_000)
    min_rating = fields.Integer(load_default=None, strict=False, validate=validate.Range(min=1, max=4))
    company_size = ChoiceField(list(jobs.COMPANY_SIZES))
    industry = IndustryField()
    job_function = JobFunctionField()
    company = OptionalCompanyField()
    sort = ChoiceField(["relevant", "most_recent"], load_default="relevant")
    page = PageField(max_page=jobs.MAX_PAGE)

    @validates_schema
    def _salary_range(self, data, **kwargs):
        # no query / location / company = every job in the United States
        # (jobs.DEFAULT_LOCATION), which is what the site shows too
        if data.get("min_salary") and data.get("max_salary") and data["min_salary"] > data["max_salary"]:
            raise ValidationError("min_salary must not exceed max_salary.", "min_salary")


class JobDetailsSchema(BaseSchema):
    job = JobField()


# ---- reference ---------------------------------------------------------------------------------------

class JobTitleAutocompleteSchema(BaseSchema):
    query = QueryField(max_length=100)


class LocationAutocompleteSchema(BaseSchema):
    query = QueryField(max_length=100)
    type = ChoiceField(list(reference.LOCATION_TYPES), load_default="all")


class EmptySchema(BaseSchema):
    pass


# ---- community ---------------------------------------------------------------------------------------

class BowlSchema(BaseSchema):
    bowl = BowlField()


class BowlPostsSchema(BaseSchema):
    bowl = BowlField()
    sort = ChoiceField(list(community.POST_SORTS), load_default="recent")
    limit = fields.Integer(load_default=20, strict=False, validate=validate.Range(min=1, max=100))


class PostSchema(BaseSchema):
    post = PostField()


class PostCommentsSchema(BaseSchema):
    post = PostField()
    sort = ChoiceField(list(community.COMMENT_SORTS), load_default="top")
    page = PageField(max_page=100)
