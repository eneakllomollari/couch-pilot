# Security Policy

## Important Notice

**Couch Pilot is designed for local network use only.** It has no built-in authentication and should never be exposed to the public internet.

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |

## Reporting a Vulnerability

If you discover a security vulnerability, please report it by:

1. **Do NOT** open a public GitHub issue
2. Email the maintainer directly or use GitHub's private vulnerability reporting
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

You can expect:
- Acknowledgment within 48 hours
- Status update within 7 days
- Fix timeline based on severity

## Security Considerations

### By Design (Not Vulnerabilities)

- **No Authentication**: This app is intended for trusted local networks only
- **Unencrypted ADB**: TV communication uses standard ADB protocol
- **Local Storage**: Credentials stored in environment variables on disk

### Recommendations

1. **Network Isolation**: Run only on trusted home networks
2. **Firewall Rules**: Block external access to port 5001
3. **Credential Security**: Protect your `.env` file with appropriate permissions
4. **Regular Updates**: Keep dependencies updated via Dependabot PRs
