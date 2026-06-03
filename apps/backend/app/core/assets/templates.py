"""
JARV Backend - Asset Template Library

Pre-built templates for common asset types to accelerate creation.
"""
from typing import Dict, Any, List
from dataclasses import dataclass
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class TemplateCategory(str, Enum):
    """Template categories"""
    MARKETING = "marketing"
    SOCIAL_MEDIA = "social_media"
    PRESENTATION = "presentation"
    DOCUMENT = "document"
    EMAIL = "email"
    WEB = "web"
    MOBILE = "mobile"
    PRINT = "print"


@dataclass
class AssetTemplate:
    """Asset template definition"""
    template_id: str
    name: str
    category: TemplateCategory
    description: str
    asset_type: str  # AssetType value
    dimensions: Dict[str, Any]
    placeholders: List[str]  # Fields that can be customized
    default_values: Dict[str, Any]
    preview_url: str
    tags: List[str]


class AssetTemplateLibrary:
    """
    Library of pre-built asset templates.

    Provides templates for common asset types to accelerate creation.
    """

    def __init__(self):
        """Initialize template library"""
        self.logger = logging.getLogger(__name__)
        self.templates = self._load_templates()

    def _load_templates(self) -> Dict[str, AssetTemplate]:
        """Load all templates"""
        templates = {}

        # Marketing Templates
        templates["social_post_square"] = AssetTemplate(
            template_id="social_post_square",
            name="Social Media Post (Square)",
            category=TemplateCategory.SOCIAL_MEDIA,
            description="Square format social media post (1080x1080)",
            asset_type="image",
            dimensions={"width": 1080, "height": 1080},
            placeholders=["headline", "subtext", "logo", "background_image"],
            default_values={
                "background_color": "#FFFFFF",
                "text_color": "#000000",
                "font": "Arial",
            },
            preview_url="/templates/previews/social_post_square.png",
            tags=["social", "instagram", "facebook", "square"],
        )

        templates["social_post_story"] = AssetTemplate(
            template_id="social_post_story",
            name="Social Media Story",
            category=TemplateCategory.SOCIAL_MEDIA,
            description="Vertical story format (1080x1920)",
            asset_type="image",
            dimensions={"width": 1080, "height": 1920},
            placeholders=["headline", "call_to_action", "background_image"],
            default_values={
                "background_color": "#000000",
                "text_color": "#FFFFFF",
            },
            preview_url="/templates/previews/social_post_story.png",
            tags=["social", "instagram", "story", "vertical"],
        )

        templates["blog_header"] = AssetTemplate(
            template_id="blog_header",
            name="Blog Post Header",
            category=TemplateCategory.WEB,
            description="Blog post header image (1200x630)",
            asset_type="image",
            dimensions={"width": 1200, "height": 630},
            placeholders=["title", "subtitle", "author", "background"],
            default_values={},
            preview_url="/templates/previews/blog_header.png",
            tags=["blog", "web", "header"],
        )

        # Presentation Templates
        templates["pitch_deck"] = AssetTemplate(
            template_id="pitch_deck",
            name="Pitch Deck",
            category=TemplateCategory.PRESENTATION,
            description="Startup pitch deck presentation (16:9)",
            asset_type="presentation",
            dimensions={"width": 1920, "height": 1080, "slides": 15},
            placeholders=[
                "company_name", "tagline", "problem", "solution",
                "market_size", "business_model", "team", "financials"
            ],
            default_values={"theme": "professional", "color_scheme": "blue"},
            preview_url="/templates/previews/pitch_deck.png",
            tags=["presentation", "startup", "pitch", "business"],
        )

        templates["product_presentation"] = AssetTemplate(
            template_id="product_presentation",
            name="Product Presentation",
            category=TemplateCategory.PRESENTATION,
            description="Product showcase presentation",
            asset_type="presentation",
            dimensions={"width": 1920, "height": 1080, "slides": 10},
            placeholders=["product_name", "features", "benefits", "pricing"],
            default_values={"theme": "modern"},
            preview_url="/templates/previews/product_presentation.png",
            tags=["presentation", "product", "showcase"],
        )

        # Document Templates
        templates["business_proposal"] = AssetTemplate(
            template_id="business_proposal",
            name="Business Proposal",
            category=TemplateCategory.DOCUMENT,
            description="Professional business proposal document",
            asset_type="document",
            dimensions={"page_size": "A4", "pages": 10},
            placeholders=[
                "company_name", "client_name", "proposal_title",
                "executive_summary", "scope", "timeline", "budget"
            ],
            default_values={"font": "Calibri", "line_spacing": 1.5},
            preview_url="/templates/previews/business_proposal.png",
            tags=["document", "proposal", "business"],
        )

        templates["technical_doc"] = AssetTemplate(
            template_id="technical_doc",
            name="Technical Documentation",
            category=TemplateCategory.DOCUMENT,
            description="Technical documentation template",
            asset_type="document",
            dimensions={"page_size": "A4"},
            placeholders=["project_name", "version", "sections"],
            default_values={"font": "Consolas", "include_code_blocks": True},
            preview_url="/templates/previews/technical_doc.png",
            tags=["document", "technical", "documentation"],
        )

        # Email Templates
        templates["newsletter"] = AssetTemplate(
            template_id="newsletter",
            name="Email Newsletter",
            category=TemplateCategory.EMAIL,
            description="HTML email newsletter template",
            asset_type="document",
            dimensions={"width": 600},
            placeholders=[
                "header_image", "headline", "articles",
                "call_to_action", "footer"
            ],
            default_values={"mobile_responsive": True},
            preview_url="/templates/previews/newsletter.png",
            tags=["email", "newsletter", "marketing"],
        )

        templates["promotional_email"] = AssetTemplate(
            template_id="promotional_email",
            name="Promotional Email",
            category=TemplateCategory.EMAIL,
            description="Promotional/sales email template",
            asset_type="document",
            dimensions={"width": 600},
            placeholders=["offer", "discount_code", "cta_button", "images"],
            default_values={},
            preview_url="/templates/previews/promotional_email.png",
            tags=["email", "promotional", "sales"],
        )

        # Web Templates
        templates["landing_page"] = AssetTemplate(
            template_id="landing_page",
            name="Landing Page",
            category=TemplateCategory.WEB,
            description="Product/service landing page",
            asset_type="document",
            dimensions={"responsive": True},
            placeholders=[
                "hero_headline", "hero_image", "features",
                "testimonials", "cta", "footer"
            ],
            default_values={"framework": "responsive"},
            preview_url="/templates/previews/landing_page.png",
            tags=["web", "landing", "marketing"],
        )

        # Mobile Templates
        templates["app_screenshot"] = AssetTemplate(
            template_id="app_screenshot",
            name="App Store Screenshot",
            category=TemplateCategory.MOBILE,
            description="Mobile app screenshot for app stores",
            asset_type="image",
            dimensions={"width": 1242, "height": 2688},
            placeholders=["app_screen", "overlay_text", "background"],
            default_values={},
            preview_url="/templates/previews/app_screenshot.png",
            tags=["mobile", "app", "screenshot"],
        )

        return templates

    def get_template(self, template_id: str) -> AssetTemplate:
        """Get template by ID"""
        return self.templates.get(template_id)

    def list_templates(
        self,
        category: TemplateCategory = None,
        asset_type: str = None,
        tags: List[str] = None,
    ) -> List[AssetTemplate]:
        """
        List templates with optional filtering.

        Args:
            category: Filter by category
            asset_type: Filter by asset type
            tags: Filter by tags

        Returns:
            List of matching templates
        """
        results = list(self.templates.values())

        if category:
            results = [t for t in results if t.category == category]

        if asset_type:
            results = [t for t in results if t.asset_type == asset_type]

        if tags:
            results = [
                t for t in results
                if any(tag in t.tags for tag in tags)
            ]

        return results

    def get_categories(self) -> List[TemplateCategory]:
        """Get all template categories"""
        return list(TemplateCategory)

    def get_template_stats(self) -> Dict[str, Any]:
        """Get template library statistics"""
        by_category = {}
        for category in TemplateCategory:
            count = sum(
                1 for t in self.templates.values()
                if t.category == category
            )
            if count > 0:
                by_category[category.value] = count

        by_type = {}
        for template in self.templates.values():
            asset_type = template.asset_type
            by_type[asset_type] = by_type.get(asset_type, 0) + 1

        return {
            "total_templates": len(self.templates),
            "by_category": by_category,
            "by_asset_type": by_type,
        }


# Global template library instance
_template_library: AssetTemplateLibrary = None


def get_template_library() -> AssetTemplateLibrary:
    """Get global template library instance"""
    global _template_library
    if _template_library is None:
        _template_library = AssetTemplateLibrary()
    return _template_library
