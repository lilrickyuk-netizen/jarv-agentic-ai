"""Field knowledge for company operator, business, finance, sales, partnerships and legal agents."""
from __future__ import annotations

from app.core.knowledge.library._base import topic

ENTRIES = [
    # ----- company operator ------------------------------------------------------------------------
    topic("company_operator", "okrs", "Setting objectives and key results", """
        Set three to five objectives per period, each an ambitious, specific end state rather than maintenance
        work, and about three key results per objective that are measurable outcomes (not activities such as
        'help' or 'analyse') with evidence of completion that is easy to find. Grade key results from 0 to 1 and
        expect around 0.6 to 0.7 on stretch goals; consistently scoring 1.0 means the goals are too safe. Make
        OKRs visible, review them during the quarter, connect team OKRs to at least one company OKR, and do not
        treat them as a to-do list or as a performance evaluation. Avoid business-as-usual or low-value
        objectives and key results that would not actually achieve the objective.""",
        ["okrs", "objectives", "key results", "goals", "planning", "quarterly", "kpis"], "okrs"),
    topic("company_operator", "uk-company-duties", "Running a UK limited company", """
        Directors must act within the company's constitution, promote its success with regard to long-term
        consequences, employees, suppliers, customers and reputation, exercise independent judgement and
        reasonable care, skill and diligence, avoid conflicts of interest, refuse benefits from third parties,
        and declare interests in transactions; on insolvency their duties shift towards creditors. Every year
        the company files annual accounts (even when dormant) and a confirmation statement with Companies House,
        and reports changes of officers, registered office, shares, charges and people with significant control.
        Directors stay responsible for records and filings even when an accountant prepares them. Filing,
        payments and binding commitments are decisions for Richard; JARV prepares and reminds.""",
        ["company", "director", "companies house", "accounts", "confirmation statement", "uk", "compliance"],
        "uk_directors"),
    topic("company_operator", "uk-tax-calendar", "The tax calendar for a UK company", """
        Corporation Tax for profits up to £1.5 million is due 9 months and 1 day after the end of the accounting
        period; larger companies pay by instalments. The Company Tax Return is due 12 months after the end of the
        period it covers and must be filed even when there is a loss or no tax to pay, with penalties for late
        filing and interest on late payment. VAT registration is required when taxable turnover goes over, or is
        expected to go over, £90,000; a registered business may deregister below £88,000. Track these dates in the
        operating plan with lead time, and confirm figures with the accountant before acting.""",
        ["tax", "corporation tax", "vat", "deadline", "hmrc", "uk", "calendar"], "uk_corp_tax"),
    topic("company_operator", "operating-metrics", "Reading the business through its numbers", """
        For a subscription product, monthly recurring revenue is the monthly-normalised value of active and past-
        due subscriptions, excluding taxes, free plans and usage-based items. MRR moves through new, expansion,
        reactivation, contraction and churn; tracking those components shows whether growth comes from new
        customers or from existing ones. Subscriber churn rate is churned subscribers in 30 days divided by
        subscribers at the start plus new ones; ARPU is MRR divided by active subscribers; lifetime value
        estimates ARPU divided by churn rate; revenue retention by cohort can exceed 100% when expansion
        outweighs churn. Review these weekly alongside the delivery and support numbers.""",
        ["mrr", "churn", "arpu", "ltv", "retention", "metrics", "revenue"], "stripe_metrics"),

    # ----- business ----------------------------------------------------------------------------------
    topic("business", "subscription-economics", "Subscription economics", """
        Express pricing decisions in their effect on MRR components: new MRR from conversions, expansion from
        upgrades, contraction from downgrades, churned MRR from cancellations and unpaid accounts, and
        reactivations. Annual plans are normalised to a monthly value. ARPU (MRR per active subscriber) and
        subscriber churn determine lifetime value (ARPU divided by churn rate), which bounds what can be spent to
        acquire a customer. Cohort revenue retention above 100% means existing customers grow faster than they
        leave, the strongest signal of a healthy subscription business. Decide whether discounts are subtracted
        from MRR and keep that definition consistent.""",
        ["pricing", "subscription", "mrr", "ltv", "churn", "unit economics", "cohort"], "stripe_metrics"),
    topic("business", "goal-setting", "Turning strategy into measurable goals", """
        Translate a business plan into a few ambitious objectives, each with about three measurable key results
        that describe outcomes (revenue reached, activation rate, retention) rather than tasks. Expect to land
        around 60 to 70% on stretch goals, keep goals visible, review mid-period, and use low scores as data for
        the next plan rather than as failure. Goals that the team would hit without effort, or that would not
        move the business if hit, should be replaced.""",
        ["strategy", "goals", "okrs", "planning", "business plan", "metrics"], "okrs"),
    topic("business", "uk-selling-online", "Selling online to UK consumers", """
        Before an order, show the business name, address and contact details, a clear description, the total
        price including taxes and delivery, payment and delivery arrangements, the minimum contract length and
        how rolling subscriptions end, and the cancellation terms. Confirm the contract promptly in a durable form.
        Consumers can cancel most distance contracts within 14 days; if they are not told about this right the
        period extends up to 12 months. For digital content delivered immediately, the customer must expressly
        agree and acknowledge that they lose the right to cancel once delivery starts. These terms belong in the
        checkout and the confirmation email.""",
        ["consumer", "checkout", "cancellation", "refund", "terms", "subscription", "uk"], "uk_online_selling"),

    # ----- finance -----------------------------------------------------------------------------------------
    topic("finance", "saas-metrics", "Calculating subscription metrics correctly", """
        MRR is the sum of the monthly-normalised value of active and past-due subscriptions; exclude taxes, free
        plans and metered usage, and treat a cancelled or unpaid subscription as churned. A plan billed yearly at
        600 contributes 50 a month. MRR growth for a period is starting MRR plus new, reactivation and expansion
        MRR minus contraction and churned MRR (adjusted for currency). Subscriber churn rate over 30 days is
        churned subscribers divided by subscribers 30 days ago plus new subscribers. ARPU is MRR over active
        subscribers; lifetime value is ARPU over churn rate. Trial conversion is trials converted divided by
        trials ended in the window. Report the definition used with every number.""",
        ["mrr", "churn rate", "arpu", "ltv", "trial conversion", "saas", "metrics"], "stripe_metrics"),
    topic("finance", "disputes", "Handling payment disputes", """
        A card dispute gives a fixed window to respond, usually 7 to 21 days; no response loses it automatically.
        Inquiries are a pre-dispute stage worth answering to avoid escalation. Read the cardholder's claim and the
        dispute category, contact the customer (a refund or credit may resolve it), and decide whether to accept
        or counter. A counter is submitted once, cannot be amended, and goes to the issuing bank, which may take
        up to three months. Submit concise evidence matched to the category (delivery or usage proof, refund and
        cancellation policies, customer communications), combined per evidence type, without links, audio or
        video. Countering adds a fee that is returned only if the dispute is won.""",
        ["dispute", "chargeback", "stripe", "evidence", "refund", "payments"], "stripe_disputes"),
    topic("finance", "uk-tax-dates", "UK company tax obligations", """
        Corporation Tax on profits up to £1.5 million is payable 9 months and 1 day after the end of the accounting
        period; profits above that are paid in instalments. The Company Tax Return is due 12 months after the end
        of the accounting period, even if there is a loss or no tax due, and taxable profit can differ from the
        accounts profit. Late filing brings penalties and late payment brings interest. VAT registration is
        mandatory once taxable turnover exceeds, or is expected to exceed, £90,000 (deregistration is possible
        below £88,000). Keep a dated calendar of these obligations, and treat any payment as a hard boundary for
        Richard.""",
        ["corporation tax", "vat", "tax return", "hmrc", "deadline", "uk", "compliance"], "uk_company_returns"),
    topic("finance", "budget-goals", "Budgets tied to goals", """
        Set financial goals as measurable key results (MRR reached, burn kept under a figure, payback period) that
        support the company's objectives, review them during the period, and expect to fall short on stretch
        targets. A budget line without a goal it serves is a candidate for removal; a goal without budget is not a
        plan.""",
        ["budget", "goals", "okrs", "planning", "spend", "finance"], "okrs"),

    # ----- sales -------------------------------------------------------------------------------------------
    topic("sales", "uk-email-outreach", "Lawful email outreach in the UK", """
        Marketing emails and texts to individuals, including sole traders and some partnerships, need prior
        consent: a clear, specific, recorded opt-in naming the business and the channel, not bundled with terms.
        The soft opt-in allows marketing your own similar products to people whose details you collected directly
        during a sale or negotiation, if you offered an opt-out at collection and include one in every message.
        Unsolicited email to corporate addresses (limited companies, LLPs) is allowed without consent, but every
        message must identify the sender and offer a simple, free way to opt out. Bought-in lists can be used only
        if their consent named your business and channel. Finding an address online is not consent.""",
        ["email", "outreach", "pecr", "consent", "b2b", "marketing", "prospecting", "uk"], "ico_email"),
    topic("sales", "deliverability", "Getting sales email delivered", """
        Authenticate the sending domain with both SPF and DKIM, keep valid forward and reverse DNS, send over TLS,
        and keep the From domain aligned with the authenticated domain. Above about 5,000 messages a day to Gmail,
        publish DMARC, add one-click unsubscribe headers to marketing mail and honour unsubscribes within two
        days. Keep the user-reported spam rate under 0.1% and never let it reach 0.3%. Cold outreach should be low
        volume, personal and relevant; sending at volume from Richard's mailbox is a hard boundary.""",
        ["email", "deliverability", "spf", "dkim", "dmarc", "spam", "outreach"], "gmail_senders"),
    topic("sales", "subscription-value", "Selling on value the customer can measure", """
        Frame proposals in terms the buyer can verify and the business can track: plan price normalised to a
        month, what an upgrade adds, and how the customer's results change. Know the product's ARPU, churn and
        trial conversion so discounts and annual terms are offered deliberately, and record every deal's value and
        stage so forecasts come from the pipeline rather than hope.""",
        ["sales", "pricing", "proposal", "upgrade", "pipeline", "value", "arpu"], "stripe_metrics"),
    topic("sales", "consumer-terms", "Terms when selling to consumers", """
        For consumer sales give the total price including taxes, contract length and how a subscription ends,
        cancellation rights (normally 14 days for distance sales, with the express waiver needed for immediately
        delivered digital content) and the business's identity and contact details before payment, then confirm
        in writing. Mis-stating these terms creates refund obligations and disputes later.""",
        ["consumer", "terms", "cancellation", "subscription", "pricing", "uk"], "uk_online_selling"),

    # ----- partnerships -----------------------------------------------------------------------------------
    topic("partnerships", "ndas", "Confidentiality before partnership talks", """
        Share confidential plans with prospective partners, investors or suppliers only after a signed NDA. Use a
        one-way NDA when only one side discloses and a mutual one when both do. Define confidential information
        (including what is said in meetings, not only marked documents), restrict use to a precise purpose (it can
        be widened later but not narrowed), allow disclosure to employees and advisers under the same terms, set a
        duration (three to five years is common, longer for know-how or customer lists), and agree governing law.
        Record what was disclosed and when. Once information is public, an NDA no longer protects it. Signing is a
        binding commitment for Richard; JARV drafts and reviews.""",
        ["nda", "confidentiality", "partner", "agreement", "disclosure", "legal"], "uk_nda"),
    topic("partnerships", "partner-goals", "Partnerships with measurable outcomes", """
        Give each partnership an objective and two or three measurable key results (referred customers, integration
        usage, co-marketing reach, revenue share) that both sides can see, review them during the period, and end
        or renegotiate partnerships whose results stay near zero. A partnership that would be fully achieved
        without effort, or that would not matter if achieved, is not worth the coordination cost.""",
        ["partnership", "goals", "okrs", "metrics", "co-marketing", "integration"], "okrs"),
    topic("partnerships", "partner-outreach", "Contacting prospective partners", """
        Outreach to corporate addresses may be sent without prior consent in the UK, but every message must
        identify the sender, give a valid contact address and offer an easy opt-out. Individuals (including sole
        traders) need consent or a qualifying soft opt-in. Keep outreach personal and specific to the partner's
        business, and record contact history in the partner pipeline.""",
        ["partner", "outreach", "email", "b2b", "pecr", "business development"], "ico_email"),

    # ----- legal ----------------------------------------------------------------------------------------------
    topic("legal", "consumer-contracts", "Consumer contract requirements", """
        UK distance sales require pre-contract information (trader identity and contact details, description,
        total price including taxes and delivery, payment and delivery arrangements, duration and termination of
        subscriptions, cancellation rights with a model form), prompt confirmation in a durable medium, and a
        14-day cancellation right for most goods and services (extended up to 12 months if the consumer was not
        told). Immediate digital content needs the consumer's express consent and acknowledgement that the right
        to cancel is lost. Some contracts are exempt (for example goods or services of £42 or less, financial
        services, passenger transport). JARV drafts terms for review; it does not give legal advice.""",
        ["terms", "consumer", "contract", "cancellation", "checkout", "legal", "uk"], "uk_online_selling"),
    topic("legal", "electronic-marketing", "Electronic marketing rules", """
        Under PECR, marketing emails and texts to individuals need specific, recorded consent naming the sender and
        channel, unless the soft opt-in applies (details collected directly during a sale or negotiation, own
        similar products, opt-out offered at collection and in every message). Corporate subscribers can be
        emailed without consent. Every message must identify the sender and offer a free, simple opt-out.
        Third-party lists are only usable where consent named the business. Draft marketing flows and records to
        make compliance demonstrable.""",
        ["pecr", "marketing", "consent", "email", "soft opt-in", "privacy", "uk"], "ico_email"),
    topic("legal", "storage-access", "Cookies and similar technologies", """
        PECR applies whenever a site or app stores information on, or reads information from, a user's device
        (cookies, local storage, pixels, SDKs). Consent is the rule, with listed exceptions: what is needed to
        transmit a communication, what is strictly necessary for a service the user requested, and, following the
        Data (Use and Access) Act, certain statistical, appearance and emergency-assistance purposes where the user
        has a simple means to object. Design consent so non-exempt storage happens only after a choice, and make
        withdrawing as easy as giving consent. Confirm current detail against the ICO guidance before launch.""",
        ["cookies", "consent", "tracking", "analytics", "pecr", "privacy", "website"], "ico_storage"),
    topic("legal", "endorsements-uk", "Advertising disclosure in the UK", """
        Content is advertising when the creator receives any payment or incentive (money, free products, trips,
        commission, affiliate links) or has a commercial or personal tie to the brand, and when promoting one's own
        products. Label it clearly and upfront with 'Ad' or 'Advert' before any click or scroll, on every story or
        format, never buried in hashtags; terms such as 'gifted', 'sp', 'collab' or a brand tag are not enough.
        Brands and creators are both responsible. Reviews must reflect genuine experience and claims need
        evidence; fake reviews breach both the CAP Code and consumer law.""",
        ["advertising", "disclosure", "influencer", "asa", "cap code", "reviews", "uk"], "asa_influencers"),
    topic("legal", "open-source-licences", "Choosing and complying with software licences", """
        Use a standard licence, never a custom one. MIT is the usual permissive choice; Apache 2.0 adds an explicit
        patent licence; GPL-3.0 keeps derivative works open; AGPL-3.0 extends that to software used over a network;
        LGPL-3.0 suits libraries that should link with proprietary code. Check compatibility before combining
        code: AGPL and GPL-3.0 combine, GPL-2.0-only does not combine directly with AGPL. Including GPL or AGPL
        code in a distributed or (for AGPL) hosted product binds the whole work to its terms, so audit
        dependencies' licences before shipping.""",
        ["license", "licence", "open source", "mit", "gpl", "apache", "compliance"], "oss_licences"),
]
