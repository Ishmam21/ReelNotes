# Anti Vibecode Security Instructions

Guidelines for implementing core security measures, credential protection, and operational safety in application development.

## Security

- Force HTTPS in your application.
- Store login system passwords as hashes rather than plain text.
- Implement bot protection on signups and public forms.
- Ensure login sessions expire so that stolen tokens do not work indefinitely.
- Implement CSRF protection.
- Make password reset links expire and ensure they only work once.
- Use a limited database key rather than the master key for your app.
- Ensure logs do not contain passwords, tokens, or card numbers.
- Enable billing alerts to be notified when an attack occurs.
- Set up automated backups.
