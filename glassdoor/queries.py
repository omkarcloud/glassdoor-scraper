"""GraphQL documents sent to www.glassdoor.com/graph.

Introspection is disabled and any unknown field fails the WHOLE operation
with a masked "Server error", so every field below was proven live
(2026-09-26) one at a time. The community documents (glassdoor/graphql/*)
are the site's own Fishbowl queries, copied verbatim from its JS bundles
with their fragments inlined and the Apollo `@client` fields removed.
"""
import json
import os
from functools import lru_cache

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "graphql")


@lru_cache(maxsize=None)
def document(name):
    """A community document from glassdoor/graphql/<name>.graphql."""
    with open(os.path.join(_DIR, name + ".graphql")) as f:
        return f.read()


class Enum(str):
    """A GraphQL enum value: written bare (DATE), not quoted ("DATE")."""


def literal(value):
    """A Python value -> a GraphQL input literal. Inputs are written inline
    because the schema's input TYPE names are unknown (introspection is
    off), which rules out typed $variables for these roots. Strings go
    through json.dumps, so user text is always escaped; None-valued keys
    are left out."""
    if value is None:
        return "null"
    if isinstance(value, Enum):
        if not value.replace("_", "").isalnum():
            raise ValueError(f"bad enum value {value!r}")
        return str(value)
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float, str)):
        return json.dumps(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(literal(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{k}: {literal(v)}" for k, v in value.items() if v is not None) + "}"
    raise TypeError(f"no GraphQL literal for {type(value).__name__}")


RATINGS = """overallRating ceoRating ceoRatingsCount businessOutlookRating recommendToFriendRating
  careerOpportunitiesRating compensationAndBenefitsRating cultureAndValuesRating
  diversityAndInclusionRating seniorManagementRating workLifeBalanceRating"""

EMPLOYER_FIELDS = """
  id name shortName website headquarters size sizeCategory revenue type yearFounded stock
  squareLogoUrl activeStatus
  bestProfile { id }
  counts { reviewCount salaryCount interviewCount benefitCount photoCount globalJobCount { jobCount } }
  overview { description mission }
  primaryIndustry { industryId industryName sectorId sectorName }
  links { overviewUrl reviewsUrl salariesUrl benefitsUrl interviewUrl jobsUrl photosUrl faqUrl locationsUrl }
  ceo { name title photoUrl }
  coverPhoto { hiResUrl }
  ratings { %s }
  awards { name source year featured }
  competitors { id shortName squareLogoUrl }
  parent { employer { id shortName } }
  subsidiaries { employer { id shortName } }
  bestPlacesToWork(onlyCurrent: false) { timePeriod tldId rank }
  bestLedCompanies(onlyCurrent: false) { id timePeriod }
  bestPlacesToWorkCEO(onlyCurrent: false) { id tldId }
  legalActionBadges { headerText }
""" % RATINGS

EMPLOYER = "query EmployerDetails($id: Int!) { employer(id: $id) { %s } }" % EMPLOYER_FIELDS

EMPLOYER_OFFICES = """query EmployerOffices($id: Int!) {
  employer(id: $id) {
    id shortName
    links { locationsUrl }
    officeAddresses { id officeLocationId addressLine1 addressLine2 cityName administrativeAreaName1 postalCode countryName }
  }
}"""

EMPLOYER_SEARCH = """query EmployerSearch($input: EmployerSearchInput) {
  employerSearchRG(employerSearchInput: $input) {
    numOfPagesAvailable
    numOfRecordsAvailable
    employerResults {
      employer {
        id shortName name squareLogoUrl website headquarters size sizeCategory
        bestProfile { id }
        counts { reviewCount salaryCount globalJobCount { jobCount } }
        primaryIndustry { industryId industryName sectorId sectorName }
        overview { description }
        ratings { %s }
        bestPlacesToWork(onlyCurrent: true) { timePeriod tldId }
        bestLedCompanies(onlyCurrent: true) { id timePeriod }
        bestPlacesToWorkCEO(onlyCurrent: true) { id tldId }
      }
      demographicRatings { category categoryRatings { categoryValue ratings { overallRating } } }
    }
  }
}""" % RATINGS

COMPANY_SALARIES = """query CompanySalaries($input: AggregatedSalaryEstimatesInput!) {
  aggregatedSalaryEstimates(aggregatedSalaryEstimatesInput: $input) {
    resultCount
    numPages
    queryLocation { id name shortName type }
    results {
      jobTitle { id text }
      salaryCount
      payPeriod
      currency { code }
      basePayStatistics { mean percentiles { ident value } }
      totalAdditionalPayStatistics { mean percentiles { ident value } }
      totalPayStatistics { mean percentiles { ident value } }
    }
  }
}"""

JOB_VIEW = """query JobDetailQuery($jl: Long!, $queryString: String, $pageTypeEnum: PageTypeEnum) {
  jobview: jobView(listingId: $jl, contextHolder: {queryString: $queryString, pageTypeEnum: $pageTypeEnum}) {
    header {
      adOrderId advertiserType ageInDays applyUrl easyApply
      employer { id name shortName squareLogoUrl }
      employerNameFromSearch expired goc gocId
      indeedJobAttribute { education educationLabel skills skillsLabel yearsOfExperienceLabel extractedJobAttributes { key value } }
      isSponsoredJob isSponsoredEmployer jobCountryId jobLink jobTitleText jobTypeKeys locId locationName
      locationType normalizedJobTitle payCurrency payPeriod payPeriodAdjustedPay { p10 p50 p90 } posted
      rating remoteWorkTypes salarySource sgocId seoJobLink
    }
    job { description discoverDate idFromSource importConfigId jobTitleId jobTitleText listingId }
    map { address cityName country lat lng locationName postalCode stateName }
    overview {
      id name shortName squareLogoUrl headquarters revenue size sizeCategory type website yearFounded
      ceo { name photoUrl }
      links { benefitsUrl overviewUrl photosUrl reviewsUrl salariesUrl }
      primaryIndustry { industryId industryName sectorId sectorName }
      ratings { careerOpportunitiesRating ceoRating ceoRatingsCount compensationAndBenefitsRating cultureAndValuesRating
                overallRating recommendToFriendRating seniorManagementRating workLifeBalanceRating }
    }
    similarJobs { relatedJobTitle }
  }
}"""

INDUSTRIES = """query IndustriesAndSectorsQuery {
  industries { industryId industryName parentSectorId }
  sectors { childIndustryIds sectorId sectorName }
}"""

EMPLOYER_RESOLVE = """query EmployerResolve($input: EmployerSearchInput) {
  employerSearchRG(employerSearchInput: $input) {
    employerResults { employer { id shortName name squareLogoUrl website counts { reviewCount } } }
  }
}"""

RESPONSES = "employerResponses { id response responseDateTime userJobTitle countHelpful }"

RATING_DISTRIBUTION = """ratingCountDistribution {
      overall { _1 _2 _3 _4 _5 } careerOpportunities { _1 _2 _3 _4 _5 } compensationAndBenefits { _1 _2 _3 _4 _5 }
      cultureAndValues { _1 _2 _3 _4 _5 } diversityAndInclusion { _1 _2 _3 _4 _5 } seniorManagement { _1 _2 _3 _4 _5 }
      workLifeBalance { _1 _2 _3 _4 _5 } recommendToFriend { RECOMMEND WONT_RECOMMEND }
    }"""

# employerReviewsRG filters only take effect with `language` set (the site
# always sends "eng"); without it every filter returns 0 rows.
REVIEWS = """query EmployerReviews {
  employerReviewsRG(employerReviewsInput: %%(input)s) {
    allReviewsCount filteredReviewsCount ratedReviewsCount numberOfPages
    queryJobTitle { id text }
    queryLocation { id name type }
    ratings { %s }
    %s
    reviews {
      reviewId reviewDateTime summary pros cons advice
      ratingOverall ratingCareerOpportunities ratingCompensationAndBenefits ratingCultureAndValues
      ratingDiversityAndInclusion ratingSeniorLeadership ratingWorkLifeBalance
      ratingRecommendToFriend ratingCeo ratingBusinessOutlook
      jobTitle { text } location { id name type } employmentStatus isCurrentJob lengthOfEmployment
      countHelpful countNotHelpful featured originalLanguageId
      employer { id shortName }
      %s
    }
  }
}""" % (RATINGS.replace("ceoRatingsCount ", ""), RATING_DISTRIBUTION, RESPONSES)

INTERVIEWS = """query EmployerInterviews {
  employerInterviewsIG(employerInterviewsInput: %%(input)s) {
    totalInterviewCount filteredInterviewCount interviewQuestionCount totalNumberOfPages newestReviewDate
    difficultySubmissionCount difficultySum
    interviewExperienceCounts { type count }
    interviewObtainedChannelCounts { type count }
    queryLocation { id name type }
    interviews {
      id reviewDateTime interviewDateTime jobTitle { text } location { id name type }
      processDescription difficulty experience outcome source durationDays
      countHelpful countNotHelpful featured
      userQuestions { id question answerCount }
      %s
    }
  }
}""" % RESPONSES

PHOTOS = """query EmployerPhotos {
  employerPhotos(employerId: %(employer_id)d, page: %(page)s) {
    totalCount
    photos { photoId caption location photoLink photoUrl2x photoUrlLarge }
  }
}"""

SALARY_ESTIMATE = """query SalaryEstimate {
  occSalaryEstimates(occSalaryEstimatesInput: %(input)s) {
    jobTitle { id text }
    queryLocation { id name type }
    payPeriod currency { code } confidence salariesCount estimateSourceUpdateTime
    basePayPercentiles { percentile value }
    additionalPayPercentiles { percentile value }
    totalPayPercentiles { percentile value }
  }
}"""

TITLE_SALARIES = """query TitleSalaries {
  aggregatedSalaryEstimates(aggregatedSalaryEstimatesInput: %(input)s) {
    resultCount numPages
    queryLocation { id name shortName type }
    results {
      employer { id shortName squareLogoUrl ratings { overallRating } counts { globalJobCount { jobCount } } }
      jobTitle { id text }
      salaryCount payPeriod currency { code }
      basePayStatistics { percentiles { ident value } }
      totalAdditionalPayStatistics { percentiles { ident value } }
      totalPayStatistics { percentiles { ident value } }
    }
  }
}"""
