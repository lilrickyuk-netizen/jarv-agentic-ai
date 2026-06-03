"""
JARV Backend - Knowledge Base System

Self-service support with articles, FAQs, and documentation.
"""
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field
from datetime import datetime
import uuid
import logging

logger = logging.getLogger(__name__)


@dataclass
class Article:
    """Knowledge base article"""
    article_id: str
    title: str
    content: str
    category: str
    tags: List[str]
    author_id: str
    created_at: datetime
    updated_at: datetime
    view_count: int = 0
    helpful_count: int = 0
    not_helpful_count: int = 0
    is_published: bool = True
    related_articles: List[str] = field(default_factory=list)


class KnowledgeBase:
    """
    Knowledge base for self-service customer support.

    Provides searchable articles, FAQs, and documentation.
    """

    def __init__(self):
        """Initialize knowledge base"""
        self.logger = logging.getLogger(__name__)
        self.articles: Dict[str, Article] = {}
        self._load_default_articles()

    def _load_default_articles(self):
        """Load default FAQ articles"""
        default_articles = [
            {
                "title": "How do I create a new workspace?",
                "content": "To create a new workspace:\n1. Navigate to Workspaces\n2. Click 'New Workspace'\n3. Enter workspace details\n4. Click 'Create'",
                "category": "Getting Started",
                "tags": ["workspace", "getting-started"],
            },
            {
                "title": "How do I reset my password?",
                "content": "To reset your password:\n1. Click 'Forgot Password' on login page\n2. Enter your email\n3. Check your email for reset link\n4. Follow the link and create new password",
                "category": "Account",
                "tags": ["password", "account", "security"],
            },
            {
                "title": "What are the different agent types?",
                "content": "JARV has 31 specialist agents including:\n- Coding agents for development\n- Debugging agents for troubleshooting\n- QA agents for testing\n- DevOps agents for deployment\n- Business agents for analytics\nAnd many more specialized agents for specific tasks.",
                "category": "Features",
                "tags": ["agents", "features"],
            },
            {
                "title": "How do I upload assets?",
                "content": "To upload assets:\n1. Go to Assets section\n2. Click 'Upload Asset'\n3. Select file and fill metadata\n4. Choose asset type and tags\n5. Click 'Upload'",
                "category": "Assets",
                "tags": ["assets", "upload", "files"],
            },
            {
                "title": "What is the pricing model?",
                "content": "JARV offers flexible pricing:\n- Free tier: Basic features\n- Pro tier: Advanced features\n- Enterprise: Custom solutions\nContact sales for detailed pricing.",
                "category": "Billing",
                "tags": ["pricing", "billing", "plans"],
            },
        ]

        for article_data in default_articles:
            self.create_article(
                title=article_data["title"],
                content=article_data["content"],
                category=article_data["category"],
                tags=article_data["tags"],
                author_id="system",
            )

    def create_article(
        self,
        title: str,
        content: str,
        category: str,
        tags: List[str],
        author_id: str,
        is_published: bool = True,
    ) -> Article:
        """Create a new knowledge base article"""
        article_id = str(uuid.uuid4())
        now = datetime.utcnow()

        article = Article(
            article_id=article_id,
            title=title,
            content=content,
            category=category,
            tags=tags,
            author_id=author_id,
            created_at=now,
            updated_at=now,
            is_published=is_published,
        )

        self.articles[article_id] = article
        self.logger.info(f"Created article: {title}")

        return article

    def get_article(self, article_id: str) -> Optional[Article]:
        """Get article by ID"""
        article = self.articles.get(article_id)
        if article:
            article.view_count += 1
        return article

    def search_articles(
        self,
        query: Optional[str] = None,
        category: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> List[Article]:
        """Search articles"""
        results = [a for a in self.articles.values() if a.is_published]

        if query:
            query_lower = query.lower()
            results = [
                a for a in results
                if query_lower in a.title.lower() or query_lower in a.content.lower()
            ]

        if category:
            results = [a for a in results if a.category == category]

        if tags:
            results = [a for a in results if any(tag in a.tags for tag in tags)]

        # Sort by helpfulness
        results.sort(
            key=lambda a: (a.helpful_count - a.not_helpful_count, a.view_count),
            reverse=True
        )

        return results

    def get_stats(self) -> Dict[str, Any]:
        """Get knowledge base statistics"""
        articles = list(self.articles.values())

        return {
            "total_articles": len(articles),
            "published_articles": sum(1 for a in articles if a.is_published),
            "total_views": sum(a.view_count for a in articles),
            "total_helpful": sum(a.helpful_count for a in articles),
        }


# Global knowledge base instance
_knowledge_base: Optional[KnowledgeBase] = None


def get_knowledge_base() -> KnowledgeBase:
    """Get global knowledge base instance"""
    global _knowledge_base
    if _knowledge_base is None:
        _knowledge_base = KnowledgeBase()
    return _knowledge_base
