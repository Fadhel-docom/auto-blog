# Cloudflare Pages build command note

Date: 2026-10-28

The Cloudflare Pages project `home-organization-ideas` uses this build command so that the Sitemap line in the deployed robots.txt points to the pages.dev address. static/robots.txt is shared with GitHub Pages and is not changed.

hugo --baseURL https://home-organization-ideas.pages.dev/ && sed -i 's|https://fadhel-docom.github.io/auto-blog/sitemap.xml|https://home-organization-ideas.pages.dev/sitemap.xml|' public/robots.txt

Build output directory: public. Production branch: main.
