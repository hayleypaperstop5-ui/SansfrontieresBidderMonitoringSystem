"""
payments.middleware — small middlewares specific to payment responses.
"""
from django.utils.deprecation import MiddlewareMixin


class StripXFrameOptionsForPdfMiddleware:
    """
    Remove X-Frame-Options from PDF responses.

    Django (and Django's SecurityMiddleware / XFrameOptionsMiddleware) sets
    X-Frame-Options: DENY on every response by default. Chrome's built-in
    PDF viewer embeds the PDF in an iframe-like element, so DENY makes the
    viewer fail silently; the browser then waits ~19 s before aborting the
    connection, producing a "Broken pipe" in the dev server log.

    Removing the header for application/pdf responses lets the browser PDF
    viewer (and Content-Disposition: attachment downloads) work correctly.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        content_type = response.get("Content-Type", "") or ""
        if content_type.startswith("application/pdf"):
            try:
                del response["X-Frame-Options"]
            except KeyError:
                pass
            try:
                del response["X-Content-Type-Options"]
            except KeyError:
                pass
        return response
