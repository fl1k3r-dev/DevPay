import uuid
from aiogram.filters.callback_data import CallbackData

class PlanAdminCallback(CallbackData, prefix="admin_plan"):
    action: str # "view", "archive", "deprecate", "activate"
    plan_id: uuid.UUID