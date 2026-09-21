"""Permission boundary only. This release has no external AI transport or credentials."""
KEY = "external_ai_allowed"


class ExternalAIPolicy:
    def __init__(self, store):
        self.store = store

    @property
    def allowed(self):
        return self.store is not None and self.store.setting(KEY, "false") == "true"

    def save(self, allowed: bool):
        if self.store is not None:
            self.store.set_setting(KEY, "true" if allowed else "false")

    def require_provider(self):
        # Future adapters must check current permission immediately before sending,
        # including retries. No callable transport is supplied in this version.
        if not self.allowed:
            raise PermissionError("외부 AI 연결이 차단되어 있습니다.")
        raise NotImplementedError("외부 AI 연결은 아직 제공되지 않습니다. 로컬 정리를 이용해 주세요.")

    @property
    def status(self):
        return ("외부 AI: 허용 설정 · 연결 기능 미제공" if self.allowed
                else "외부 AI: 차단 · 로컬에서만 정리")
