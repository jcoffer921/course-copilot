from rest_framework.throttling import UserRateThrottle


class AIUserBurstThrottle(UserRateThrottle):
    scope = "ai_burst"


class AIUserDailyThrottle(UserRateThrottle):
    scope = "ai_daily"
