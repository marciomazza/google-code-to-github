> **Issue migrated from {{ issue.url }}** (with original status *{{ issue.status }}*)
> originally created by {{ github_user(issue.author) }} in {{ issue.date }}

{{ issue.content }}
{% for attachment in issue.attachments %}
> **Attachment: [{{ attachment.name }}]({{ github_download_url(attachment.name) }})** ({{ attachment.human_readable_size }})
{% endfor %}
{% if issue.comments %}
**Original comments:**
{% for comment in issue.comments %}
***
> **Comment** by {{ github_user(comment.author) }} in {{ comment.date }}
> *migrated from {{ comment.url }}*
>
{{ blockquote(comment.content) }}
{% for attachment in comment.attachments %}
>> **Attachment: [{{ attachment.name }}]({{ github_download_url(attachment.name) }})** ({{ attachment.human_readable_size }})
{% endfor %}
{% endfor %}
{%- endif %}
