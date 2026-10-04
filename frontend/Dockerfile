FROM nginx:1.27-alpine

COPY frontend/nginx.conf /etc/nginx/conf.d/default.conf
COPY frontend/index.html /usr/share/nginx/html/index.html
COPY frontend/index.css /usr/share/nginx/html/index.css
COPY frontend/index.js /usr/share/nginx/html/index.js
COPY frontend/co2.js /usr/share/nginx/html/co2.js

EXPOSE 80
