class OAuthAuthorizationRequired(Exception):
    def __init__(self, url: str):
        self.url = url
