from django.db import models


class State(models.Model):
    """Indian State / Union Territory."""
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=10, blank=True, default="", help_text="State code e.g. MH, GJ")

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class District(models.Model):
    """District within a State."""
    name = models.CharField(max_length=100)
    state = models.ForeignKey(
        State,
        on_delete=models.CASCADE,
        related_name='districts',
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.state.name})" if self.state else self.name


class Tahsil(models.Model):
    """Tahsil / Taluka within a District."""
    name = models.CharField(max_length=100)
    district = models.ForeignKey(
        District,
        on_delete=models.CASCADE,
        related_name='tahsils',
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ['name']
        verbose_name = 'Tahsil'
        verbose_name_plural = 'Tahsils'

    def __str__(self):
        return f"{self.name} ({self.district.name})" if self.district else self.name

class Village(models.Model):
    """Village within a Tahsil."""
    name = models.CharField(max_length=100)
    tahasil = models.ForeignKey(Tahsil, on_delete=models.CASCADE, related_name='villages', null=True, blank=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Village'
        verbose_name_plural = 'Villages'

    def __str__(self):
        return f"{self.name} ({self.tahasil.name})" if self.tahasil else self.name