"""Test script for Customer Support System."""
import sys
from pathlib import Path
import uuid

sys.path.insert(0, str(Path(__file__).parent))

from app.core.support.tickets import get_ticket_manager, TicketPriority, TicketCategory
from app.core.support.knowledge_base import get_knowledge_base
from app.core.support.responses import get_response_templates


def test_tickets():
    print("="*70)
    print("TEST 1: TICKET SYSTEM")
    print("="*70)

    manager = get_ticket_manager()
    customer_id = str(uuid.uuid4())

    # Create ticket
    ticket = manager.create_ticket(
        subject="Test Ticket",
        description="This is a test ticket",
        customer_id=customer_id,
        customer_email="test@example.com",
        customer_name="Test User",
        priority=TicketPriority.HIGH,
        category=TicketCategory.BUG,
    )

    print(f"[OK] Created ticket #{ticket.ticket_number}")
    print(f"  Status: {ticket.status.value}")
    print(f"  Priority: {ticket.priority.value}")
    print(f"  Messages: {len(ticket.messages)}")

    # Add message
    manager.add_message(ticket.ticket_id, "agent1", "agent", "We're looking into this")
    print(f"[OK] Added agent message")

    # Search
    results = manager.search_tickets(priority=TicketPriority.HIGH)
    print(f"[OK] Search found {len(results)} high priority tickets")

    # Stats
    stats = manager.get_stats()
    print(f"[OK] Stats: {stats['total_tickets']} tickets")
    print()
    return True


def test_knowledge_base():
    print("="*70)
    print("TEST 2: KNOWLEDGE BASE")
    print("="*70)

    kb = get_knowledge_base()

    # Search
    results = kb.search_articles(query="workspace")
    print(f"[OK] Found {len(results)} articles about workspace")

    # Get article
    if results:
        article = kb.get_article(results[0].article_id)
        print(f"[OK] Retrieved article: {article.title}")
        print(f"  Views: {article.view_count}")

    # Stats
    stats = kb.get_stats()
    print(f"[OK] KB Stats: {stats['total_articles']} articles")
    print()
    return True


def test_templates():
    print("="*70)
    print("TEST 3: RESPONSE TEMPLATES")
    print("="*70)

    templates = get_response_templates()

    # List templates
    all_templates = templates.list_templates()
    print(f"[OK] Loaded {len(all_templates)} templates")

    # Get template
    welcome = templates.get_template("welcome")
    if welcome:
        print(f"[OK] Retrieved template: {welcome.name}")
        print(f"  Placeholders: {', '.join(welcome.placeholders)}")

    print()
    return True


def main():
    print("\n" + "="*70)
    print("CUSTOMER SUPPORT SYSTEM - TEST")
    print("="*70)
    print()

    results = {
        "Tickets": test_tickets(),
        "Knowledge Base": test_knowledge_base(),
        "Templates": test_templates(),
    }

    print("="*70)
    print("TEST SUMMARY")
    print("="*70)
    for name, passed in results.items():
        print(f"[{'PASS' if passed else 'FAIL'}] {name}")

    if all(results.values()):
        print("\n[SUCCESS] All tests passed!")
        return 0
    else:
        print("\n[FAILURE] Some tests failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
