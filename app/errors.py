class ValidationError(Exception):
    status = 400


class UnsupportedVendorError(ValidationError):
    pass


class ParsingError(ValidationError):
    pass


class VendorAPIError(Exception):
    def __init__(self, message, status=502):
        self.message = message
        self.status = status
        super().__init__(message)
