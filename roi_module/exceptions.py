"""Custom exceptions for the ROI module."""


class ROINotFoundError(Exception):
    def __init__(self, roi_id: str) -> None:
        super().__init__(f"ROI '{roi_id}' not found")
        self.roi_id = roi_id


class ROILimitExceededError(Exception):
    def __init__(self, camera_id: str, limit: int) -> None:
        super().__init__(f"Camera '{camera_id}' has reached the ROI limit of {limit}")
        self.camera_id = camera_id
        self.limit = limit


class InvalidPolygonError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(f"Invalid polygon: {reason}")
        self.reason = reason
