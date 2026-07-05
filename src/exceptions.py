class ServiceException(Exception):
    """Базовое исключение для нашей бизнес-логики"""
    pass


class PlanNotFoundError(ServiceException):
    def __init__(self, plan_id):
        super().__init__(f"Тарифный план с ID {plan_id} не найден")


class SubscriptionNotFoundError(ServiceException):
    def __init__(self, subscription_id):
        super().__init__(f"Подписка с ID {subscription_id} не найдена")


class InvalidStatusTransitionError(ServiceException):
    def __init__(self, current_status, target_status):
        super().__init__(f"Нельзя перевести подписку из статуса {current_status} в статус {target_status}")