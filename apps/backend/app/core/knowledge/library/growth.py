"""Field knowledge for marketing, growth, support, onboarding, community, analytics, content and creation agents."""
from __future__ import annotations

from app.core.knowledge.library._base import topic

ENTRIES = [
    # ----- marketing --------------------------------------------------------------------------------
    topic("marketing", "uk-ad-disclosure", "Clear advertising and influencer disclosure", """
        Any content where a creator was paid or given something (money, free products, trips, commission,
        affiliate links or discount codes) or has a business or personal tie to the brand is advertising and
        must say so. Put 'Ad' or 'Advert' at the very start, visible without clicking 'more' or scrolling, on
        every story and every format; do not rely on 'gifted', 'sp', 'spon', 'collab', 'in partnership with' or a
        brand tag. Brands share responsibility and must not discourage labelling. Testimonials and reviews must be
        genuine, claims must be substantiated, and fake reviews are unlawful.""",
        ["advertising", "influencer", "disclosure", "#ad", "asa", "reviews", "social"], "asa_influencers"),
    topic("marketing", "email-consent", "Email marketing permissions", """
        Email and SMS marketing to individuals needs prior, specific consent naming the business and channel, or
        the soft opt-in (contact details collected directly during a sale or negotiation, marketing only similar
        own products, opt-out offered at collection and in every message). Consent must be an active choice
        (no pre-ticked boxes), separate from terms, recorded (who, when, how) and easy to withdraw. Corporate
        addresses can receive marketing without consent but every message must identify the sender and offer a
        free opt-out. Bought lists are only usable when their consent named the business.""",
        ["email marketing", "consent", "newsletter", "pecr", "soft opt-in", "unsubscribe", "uk"], "ico_email"),
    topic("marketing", "email-deliverability", "Email deliverability requirements", """
        Gmail requires every sender to authenticate with SPF and DKIM, have valid forward and reverse DNS, use TLS,
        follow RFC 5322 formatting and keep spam complaints below 0.3%. Bulk senders (around 5,000 messages a day
        to Gmail) must also publish DMARC with alignment, add one-click List-Unsubscribe to marketing messages and
        process unsubscribes within 48 hours, and should keep the spam rate under 0.1%. Monitor reputation in
        Postmaster Tools. Mass sending from Richard's accounts is a hard boundary.""",
        ["email", "deliverability", "spf", "dkim", "dmarc", "unsubscribe", "spam rate"], "gmail_senders"),
    topic("marketing", "ai-assisted-content", "Publishing AI-assisted marketing content", """
        Generated text can contain confident errors, so fact-check every claim before publishing and review the
        metadata too (titles, descriptions, structured data, alt text), since it appears in search results.
        Producing many pages without adding value for readers is scaled content abuse and violates search spam
        policy. Where readers would care, explain how content was made; label AI-generated product titles,
        descriptions and images as required by shopping platforms.""",
        ["ai content", "seo", "fact-check", "landing page", "metadata", "marketing"], "google_ai_content"),

    # ----- growth ---------------------------------------------------------------------------------------
    topic("growth", "ab-testing", "Running experiments that tell the truth", """
        Decide the sample size or stopping rule before an experiment starts and do not stop the first time the
        result looks significant: checking repeatedly and stopping at the first significant result can declare a
        winner most of the time even when there is no real difference. Either analyse once at the planned sample
        size, or use a sequential or Bayesian expected-loss rule designed for monitoring, with a maximum sample
        size and an 'inconclusive' outcome. Base the plan on a measured baseline, remember that traffic is not
        stationary, and judge results by business impact as well as statistics.""",
        ["a/b test", "experiment", "significance", "sample size", "peeking", "conversion"], "ab_testing"),
    topic("growth", "app-store-tests", "Optimising the App Store product page", """
        App Store product page optimisation tests up to three alternative versions of the icon, screenshots and
        preview videos against the original, with a chosen share of traffic split evenly across treatments and each
        visitor seeing one version for up to 90 days. Change few elements per treatment so the cause of a result is
        clear; more treatments or localisations need longer to conclude. Act only when a treatment is better or
        worse than the baseline with at least 90% confidence. New metadata needs App Review, and alternative icons
        must ship in the app binary.""",
        ["app store", "aso", "product page", "screenshots", "icon", "experiment", "conversion"], "apple_ppo"),
    topic("growth", "retention-metrics", "Growth that compounds: retention and expansion", """
        Break MRR growth into new, expansion, reactivation, contraction and churned MRR to see where growth really
        comes from. Track subscriber churn (churned in 30 days over starting plus new subscribers), trial
        conversion (converted over ended trials in the window) and cohort revenue retention, which exceeds 100%
        when upgrades outweigh cancellations. Improving retention raises lifetime value (ARPU over churn) and makes
        every acquisition channel more valuable.""",
        ["retention", "churn", "expansion", "cohort", "trial conversion", "growth", "mrr"], "stripe_metrics"),
    topic("growth", "growth-okrs", "Setting growth goals", """
        Express growth goals as an objective with about three measurable outcome key results (activated users,
        trial conversion, retained revenue) instead of activities (posts published, campaigns run). Aim for
        stretch targets where 60 to 70% attainment is a good result, and revisit within the quarter as experiments
        report.""",
        ["growth", "goals", "okrs", "kpis", "targets", "activation"], "okrs"),

    # ----- customer support -----------------------------------------------------------------------------
    topic("customer_support", "clear-replies", "Writing replies people understand", """
        Use plain English: short, common words ('buy', not 'purchase'), sentences under about 25 words, paragraphs
        of no more than five sentences, active voice, and 'you' for the reader. Avoid jargon and internal terms,
        and explain any specialist term the first time. Prefer full forms over negative contractions such as
        'can't', which some readers misread. Use 'must' only for real requirements, 'need to' for steps and 'can'
        for options. Put the answer or the next step first.""",
        ["reply", "plain english", "tone", "support", "writing", "customer"], "govuk_clear_language"),
    topic("customer_support", "refunds-cancellations", "Refunds and cancellations", """
        UK consumers can usually cancel a distance purchase within 14 days without giving a reason (up to 12
        months if they were never told about the right). Digital content delivered immediately is not cancellable
        only if the customer expressly agreed and acknowledged losing the right before delivery started. When a
        customer threatens or files a card dispute, respond quickly: a refund or credit often resolves it, and a
        dispute left unanswered is lost. Refunds and credits are commitments; follow the workspace rule or ask
        Richard.""",
        ["refund", "cancellation", "chargeback", "dispute", "consumer rights", "billing"], "uk_online_selling"),
    topic("customer_support", "dispute-prevention", "Preventing chargebacks from support", """
        Most card disputes start as a customer who could not get an answer. Answer billing questions fast, explain
        charges clearly, and offer a refund or credit where the complaint is reasonable before the customer goes to
        their bank. Keep a record of every conversation, delivery and usage evidence, and the policies the customer
        accepted, because a dispute response is a single submission of concise evidence and cannot be amended.""",
        ["chargeback", "dispute", "billing", "refund", "evidence", "support"], "stripe_disputes"),
    topic("customer_support", "error-messages", "Helping users recover from problems", """
        Good help describes the problem in plain language, says precisely what went wrong without error codes,
        and gives a concrete way to fix it. Keep users informed about what is happening (status, timescales), give
        them a way out or to undo, and point to concise, task-focused help. Patterns in tickets that show users
        hitting the same error are design problems to report, not just tickets to close.""",
        ["errors", "troubleshooting", "help", "usability", "support", "feedback"], "nielsen_heuristics"),

    # ----- onboarding -----------------------------------------------------------------------------------
    topic("onboarding", "usability-heuristics", "Usability principles for first-run experiences", """
        Keep new users informed of progress; use their words, not internal terms; let them skip, go back and undo;
        follow platform conventions; prevent errors with sensible defaults and confirmation before risky actions;
        show options rather than making users remember them; offer shortcuts without confusing beginners; remove
        anything that is not needed for the first success; explain errors plainly with a fix; and keep help
        searchable and task-focused. Onboarding that needs a long tour usually signals interface problems.""",
        ["onboarding", "usability", "heuristics", "first run", "ux", "activation", "tour"], "nielsen_heuristics"),
    topic("onboarding", "accessible-onboarding", "Accessible onboarding flows", """
        Every onboarding step must work by keyboard with visible focus, have labelled fields with errors described
        in text, meet contrast minimums (4.5:1 for text), reflow at narrow widths and 200% zoom, and announce
        progress and status changes to assistive technology. Sign-up and sign-in must not depend on remembering or
        transcribing information without an alternative: support password managers, paste and passkeys or email
        links.""",
        ["accessibility", "onboarding", "sign up", "forms", "wcag", "keyboard"], "wcag22"),
    topic("onboarding", "onboarding-copy", "Onboarding copy", """
        Write each step in plain English: one short instruction per screen, the action first, 'you' for the user,
        familiar words, and no jargon. Explain any necessary term the first time it appears. Say what happens next
        and how long it takes.""",
        ["copy", "onboarding", "plain english", "microcopy", "instructions"], "govuk_clear_language"),
    topic("onboarding", "activation-tests", "Testing onboarding changes", """
        Measure activation before changing onboarding, then test one change at a time with a sample size or
        stopping rule fixed in advance; repeated peeking produces false winners. Prefer outcome metrics such as
        users reaching their first success within a set time over clicks on tour steps.""",
        ["activation", "experiment", "a/b test", "onboarding", "metrics"], "ab_testing"),

    # ----- community ----------------------------------------------------------------------------------
    topic("community", "building-community", "Growing a healthy community", """
        Welcome newcomers with clear, current documentation and a code of conduct that states expectations and
        consequences. Label beginner-friendly tasks (good first issues) with enough context to start, include
        non-code ways to help, respond promptly, and recognise all kinds of contributions publicly. Develop
        contributor levels, a core group who onboard others, and a triage team with a guide. Prepare for conflict
        before it happens, apply the code of conduct consistently, and keep communication open through forums,
        chat and regular updates.""",
        ["community", "contributors", "code of conduct", "good first issue", "recognition", "moderation"],
        "community_building"),
    topic("community", "announcements", "Writing community updates", """
        Write updates in plain English: lead with what changed and what members need to do, keep sentences short,
        avoid internal jargon, and address readers as 'you'. Link to the details rather than pasting them, and say
        when the next update will come.""",
        ["announcement", "update", "writing", "community", "plain english"], "govuk_clear_language"),
    topic("community", "sponsored-posts", "Sponsored and partner posts in the community", """
        When a community post promotes a partner, an affiliate product or the company's own paid offering, label it
        as an ad at the start. Members who post about the product in return for rewards must disclose it too; a
        brand tag or 'collab' is not enough.""",
        ["sponsored", "disclosure", "community", "partner", "affiliate", "advertising"], "asa_influencers"),

    # ----- analytics ----------------------------------------------------------------------------------
    topic("analytics", "experiment-analysis", "Analysing experiments", """
        Fix the analysis plan before data arrives: the metric, minimum effect worth detecting, sample size or
        stopping rule, and maximum duration. Do not repeatedly test for significance and stop at the first
        positive; that inflates false winners dramatically. If monitoring continuously, use a method built for it
        (sequential or Bayesian expected loss) and allow an inconclusive result. Report effect sizes with
        uncertainty and check sensitivity to the baseline estimate.""",
        ["experiment", "a/b test", "statistics", "significance", "analysis", "sample size"], "ab_testing"),
    topic("analytics", "subscription-reporting", "Subscription reporting definitions", """
        State definitions with every figure: MRR as monthly-normalised active and past-due subscriptions excluding
        tax, free plans and usage; churn rate as churned subscribers in 30 days over starting plus new subscribers;
        ARPU as MRR over active subscribers; lifetime value as ARPU over churn rate; trial conversion over trials
        ended in the window; cohort retention by start month, with revenue retention able to exceed 100%. Note
        the time zone of monthly boundaries, since reports and dashboards can differ.""",
        ["mrr", "churn", "cohort", "retention", "reporting", "definitions", "dashboard"], "stripe_metrics"),
    topic("analytics", "percentiles", "Summarising performance data", """
        Use percentiles rather than averages for latency and other skewed measures: the median shows the typical
        case and the 95th or 99th percentile the slow tail an average hides. Do not assume a normal distribution
        without checking. Standardise each indicator's definition (window, which events count, where measured) so
        numbers are comparable over time.""",
        ["percentiles", "latency", "statistics", "distribution", "metrics", "reporting"], "sre_slos"),
    topic("analytics", "app-store-analytics", "Reading App Store test results", """
        App Store product page tests report impressions, conversion rate, percentage improvement and confidence for
        each treatment against a chosen baseline. Wait for at least 90% confidence that a treatment is better or
        worse before acting, and remember that more treatments and localisations need more traffic to conclude.""",
        ["app store", "conversion", "test results", "confidence", "analytics"], "apple_ppo"),

    # ----- content ------------------------------------------------------------------------------------
    topic("content", "ai-content-quality", "Quality standards for AI-assisted content", """
        Treat generated drafts as drafts: verify every factual claim, figure and quote, since models can produce
        plausible errors, and review titles, descriptions, structured data and alt text as carefully as body text.
        Publish only content that adds value for readers; mass-producing pages to attract search traffic is
        scaled content abuse. Where it matters to readers, explain how content was produced.""",
        ["ai content", "fact-check", "quality", "seo", "publishing", "blog"], "google_ai_content"),
    topic("content", "plain-english", "Writing plain English", """
        Write for everyone, including readers with low literacy or English as an additional language, and
        specialists who still prefer plain words. Keep sentences under about 25 words and paragraphs to five
        sentences, use active voice, choose short familiar words and the terms readers search for, explain
        specialist terms once, and avoid buzzwords that hide what is happening.""",
        ["writing", "plain english", "clarity", "style", "readability", "content"], "govuk_clear_language"),
    topic("content", "docs-style", "Technical content style", """
        For technical articles and tutorials: address the reader as 'you', use active voice, sentence-case
        headings, numbered steps for procedures, code font for code and commands, descriptive link text, and
        conditions before instructions. Write for a global audience and keep content accessible with alt text and
        real headings.""",
        ["technical writing", "tutorial", "style", "headings", "code", "documentation"], "google_style"),
    topic("content", "content-images", "Images in content", """
        Prefer vector (SVG) for logos, icons and diagrams; use JPEG, WebP or AVIF for photos with a fallback for
        older browsers; avoid PNG for photos because of size; use video rather than GIF for animation; never put
        text inside images. Serve images sized for the display, and give every meaningful image alt text.""",
        ["images", "svg", "webp", "avif", "performance", "alt text", "content"], "image_formats"),

    # ----- creation -----------------------------------------------------------------------------------
    topic("creation", "image-formats", "Choosing image formats", """
        Use SVG for geometric artwork (logos, icons, simple illustrations) because it stays sharp at any size; do
        not use it for photographs. For photos use JPEG for universal support or WebP and AVIF for smaller files,
        with a JPEG or PNG fallback; reserve PNG for lossless needs and transparency where WebP is unavailable.
        Use video instead of GIF for animation. Keep text out of images and use web fonts. Test quality settings
        for the best size, and produce responsive sizes for high-density screens.""",
        ["image", "svg", "png", "jpeg", "webp", "avif", "assets", "design"], "image_formats"),
    topic("creation", "font-licensing", "Using open-licensed fonts", """
        Fonts under the SIL Open Font License can be used commercially in logos, print, apps, games and websites,
        embedded in documents and apps, and self-hosted as webfonts. They may not be sold on their own. Keep the
        copyright notice and licence text with distributed font files (and in an app's credits). A modified font
        must stay under the OFL and must not use the original's Reserved Font Name without permission.""",
        ["fonts", "ofl", "typography", "licence", "webfonts", "assets"], "ofl_faq"),
    topic("creation", "accessible-design", "Designing accessible visuals", """
        Make text contrast at least 4.5:1 (3:1 for large text) and UI component boundaries and states at least
        3:1; never use colour as the only signal; provide text alternatives for meaningful images and mark
        decorative ones as such; keep pointer targets at least 24 by 24 CSS pixels; and design layouts that reflow
        at 320 CSS pixels and remain usable at 200% zoom.""",
        ["accessibility", "contrast", "colour", "design", "alt text", "ui"], "wcag22"),
    topic("creation", "usable-design", "Design principles for interfaces", """
        Show system status, speak the user's language, allow undo, stay consistent with platform conventions,
        prevent errors, favour recognition over recall, support shortcuts for experts, keep designs minimal so
        important content stands out, explain errors with a fix, and keep help task-focused.""",
        ["ui", "ux", "design", "heuristics", "interface", "screens"], "nielsen_heuristics"),
]
