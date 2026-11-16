"""
The contact reader keeps a phone number only when it is valid in its country's numbering plan, checked with Google's
libphonenumber (the phonenumbers package the image installs). Real pages' numbers; no site is read.
"""
from __future__ import annotations

from app.core.internet import contacts


def test_a_number_one_digit_short_is_never_kept_and_real_numbers_are():
    import phonenumbers  # noqa: F401 - the image ships it: this test fails if it is missing

    # 16 November: Zizzi's site prints a Guildford number one digit short; it was counted as a way to contact them.
    assert not contacts._phone_ok("01483 66420")
    for good in ("01483 664200", "020 7946 0018", "+44 20 7946 0018", "0161 234 5678", "0330 123 4567",
                 "(212) 736-3100", "+1 212 736 3100"):   # a real, published US number (the Empire State Building)
        assert contacts._phone_ok(good), good
    # 16 November, Richard's machine: libphonenumber rejects the 555-01xx range reserved for fiction, as it should.
    for fiction in ("(201) 555-0123", "01483 66420"):
        assert not contacts._phone_ok(fiction), fiction
    page = ('<footer>Call us on 01483 66420 or <a href="tel:+442079460018">020 7946 0018</a>. '
            '<a href="mailto:hello@zizzi.co.uk">Email</a></footer>')
    found = contacts.extract(page, "https://www.zizzi.co.uk")
    assert [contacts._digits(p) for p in found["phones"]] == ["02079460018"] and found["emails"] == ["hello@zizzi.co.uk"]
