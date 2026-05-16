"""
StatsFlow Services Package
---------------------------
Business logic layer — contains all core computation modules.

Services:
  - health_score        : Multi-dimensional data quality scoring (0–100)
  - cleaning_engine     : Missing-value imputation & outlier treatment
  - pipeline_generator  : Exportable Python/Pandas script generation
  - visualization_service: Chart-ready payload computation
  - insights_service    : SLR-based auto trend highlights
  - chatbot_service     : Anthropic Claude agentic integration
"""

from app.services.health_score        import compute_health_score, get_score_label
from app.services.cleaning_engine     import CleaningEngine
from app.services.pipeline_generator  import generate_pipeline_script
from app.services.visualization_service import generate_chart_data
from app.services.insights_service    import generate_insights
from app.services.chatbot_service     import chat_with_dataset

__all__ = [
    "compute_health_score",
    "get_score_label",
    "CleaningEngine",
    "generate_pipeline_script",
    "generate_chart_data",
    "generate_insights",
    "chat_with_dataset",
]