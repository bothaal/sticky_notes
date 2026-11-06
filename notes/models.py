from django.conf import settings
from django.db import models


class Note(models.Model):
    """A sticky note belonging to a single user."""

    title = models.CharField(max_length=100)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notes",
    )

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return str(self.title)
