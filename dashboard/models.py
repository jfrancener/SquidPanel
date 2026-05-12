from django.db import models

class DomainRule(models.Model):
    RULE_CHOICES = [
        ('none', 'Nenhuma'),
        ('block', 'Blacklist'),
        ('allow', 'Whitelist'),
        ('hide', 'Oculto'),
    ]
    domain = models.CharField(max_length=255, unique=True)
    rule_type = models.CharField(max_length=10, choices=RULE_CHOICES, default='none')
    is_verified = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.domain} - {self.get_rule_type_display()}"
