# degra.af
DeGra.af website - Family profiles for the de Graaf family.

## Setup
This is a static website built with Bootstrap 5. To deploy:
1. Upload all files to your web server
2. Ensure Apache mod_rewrite and mod_headers are enabled for .htaccess
3. Configure SSL/HTTPS for your domain

## Features
- Modern Bootstrap 5 responsive design
- Profiles for Geert, Mart, and Lisa de Graaf
- Security best practices (.htaccess with CSP, HSTS)
- SEO optimized (sitemap.xml, robots.txt, meta tags)
- Privacy policy and security.txt

## Security
- Contact: security@degra.af (see .well-known/security.txt)
- HTTPS enforced via .htaccess
- Content Security Policy implemented
- Security headers configured

## Files Structure
```
/
├── index.html          # Main page
├── privacy.html        # Privacy policy
├── robots.txt          # Search engine instructions
├── sitemap.xml         # Site structure for SEO
├── .htaccess          # Apache configuration
├── .well-known/
│   └── security.txt   # Security contact info
├── img/               # Profile images
└── LICENSE            # MIT License
```

## License
MIT License - see LICENSE file for details.
