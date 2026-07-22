from pipeline.icp_persona import person_fit


def fit(title, level="", func=""):
    return person_fit({"title": title, "management_level": level, "job_function": func})["is_fit"]


# --- excluded roles: never a target, even at a perfect company -----------------------
def test_engineer_rejected():
    assert fit("Principal Software Engineer", "Non Manager") is False   # the Kyle case
    assert fit("VP Engineering", "VP Level Exec") is False
    assert fit("Staff Data Scientist") is False
    assert fit("DevOps Lead") is False

def test_it_and_security_rejected():
    assert fit("IT Manager") is False
    assert fit("Director of Information Technology", "Director") is False
    assert fit("Head of Security", "VP Level Exec") is False

def test_sales_broker_realtor_rejected():
    assert fit("Sales Director", "Director") is False
    assert fit("Realtor") is False
    assert fit("Account Executive") is False
    assert fit("VP of Sales", "VP Level Exec") is False

def test_risk_service_finance_hr_rejected():
    assert fit("Risk Manager") is False
    assert fit("Customer Service Manager") is False
    assert fit("Customer Success Director", "Director") is False
    assert fit("VP Finance", "VP Level Exec") is False
    assert fit("Head of Talent Acquisition") is False

def test_salesforce_not_confused_with_sales():
    # word-boundary: "Salesforce Marketing Cloud Manager" is a marketer, not sales
    assert fit("Salesforce Marketing Cloud Manager") is True


# --- marketing family: Manager level and above --------------------------------------
def test_marketing_manager_and_up_accepted():
    assert fit("Marketing Manager") is True
    assert fit("Head of Marketing") is True
    assert fit("Demand Generation Manager") is True
    assert fit("Content Marketing Manager") is True
    assert fit("Director of Growth", "Director") is True
    assert fit("VP Marketing", "VP Level Exec") is True
    assert fit("Chief Marketing Officer", "C Level Exec") is True
    assert fit("Head of ABM") is True
    assert fit("Marketing Operations Manager") is True   # ops token must not exclude

def test_junior_marketing_rejected():
    assert fit("Marketing Specialist") is False
    assert fit("Marketing Coordinator") is False
    assert fit("Marketing Analyst") is False
    assert fit("Marketing Intern") is False


# --- product management: Senior and above -------------------------------------------
def test_senior_product_accepted():
    assert fit("Senior Product Manager") is True
    assert fit("Principal Product Manager") is True
    assert fit("Group Product Manager") is True
    assert fit("Director of Product", "Director") is True
    assert fit("VP of Product", "VP Level Exec") is True
    assert fit("Chief Product Officer", "C Level Exec") is True
    assert fit("Product Marketing Manager") is True   # product marketing = marketing

def test_plain_and_junior_product_rejected():
    assert fit("Product Manager") is False
    assert fit("Associate Product Manager") is False
    assert fit("Product Analyst") is False


def test_missing_title_rejected():
    assert person_fit({})["is_fit"] is False
    assert person_fit({"title": ""})["is_fit"] is False
