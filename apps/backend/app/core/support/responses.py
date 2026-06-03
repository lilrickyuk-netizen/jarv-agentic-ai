"""
JARV Backend - Response Templates

Canned responses and templates for faster support.
"""
from typing import Dict, List
from dataclasses import dataclass


@dataclass
class ResponseTemplate:
    """Pre-written response template"""
    template_id: str
    name: str
    category: str
    content: str
    placeholders: List[str]


class ResponseTemplates:
    """Library of response templates for support agents"""

    def __init__(self):
        """Initialize with default templates"""
        self.templates = self._load_default_templates()

    def _load_default_templates(self) -> Dict[str, ResponseTemplate]:
        """Load default response templates"""
        templates = {}

        templates["welcome"] = ResponseTemplate(
            template_id="welcome",
            name="Welcome Message",
            category="greeting",
            content="Hello {{customer_name}},\n\nThank you for contacting JARV support. "
                   "I'm here to help you with your inquiry.\n\nBest regards,\n{{agent_name}}",
            placeholders=["customer_name", "agent_name"],
        )

        templates["resolved"] = ResponseTemplate(
            template_id="resolved",
            name="Issue Resolved",
            category="resolution",
            content="Hi {{customer_name}},\n\nI'm glad we could resolve your issue. "
                   "If you have any other questions, feel free to reach out.\n\n"
                   "Best regards,\n{{agent_name}}",
            placeholders=["customer_name", "agent_name"],
        )

        templates["investigating"] = ResponseTemplate(
            template_id="investigating",
            name="Under Investigation",
            category="status",
            content="Hi {{customer_name}},\n\nWe're currently investigating this issue "
                   "and will update you within {{timeframe}}. Thank you for your patience.\n\n"
                   "Best regards,\n{{agent_name}}",
            placeholders=["customer_name", "timeframe", "agent_name"],
        )

        return templates

    def get_template(self, template_id: str) -> ResponseTemplate:
        """Get template by ID"""
        return self.templates.get(template_id)

    def list_templates(self, category: str = None) -> List[ResponseTemplate]:
        """List all or filtered templates"""
        templates = list(self.templates.values())
        if category:
            templates = [t for t in templates if t.category == category]
        return templates


# Global instance
_response_templates: ResponseTemplates = None


def get_response_templates() -> ResponseTemplates:
    """Get global response templates instance"""
    global _response_templates
    if _response_templates is None:
        _response_templates = ResponseTemplates()
    return _response_templates
