# Local and self-hosted serving of the web app. On AWS the same dist/ goes to S3 + CloudFront; on Azure
# the `azure` target below runs in Container Apps behind Front Door (ADR-023). The last stage stays the
# default that Compose builds.
FROM node:24.21.0-alpine AS build
WORKDIR /app
COPY package.json package-lock.json .npmrc ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

# nginx renders the template at start: the CSP, the Front Door id and /config.json come from the environment,
# so one image serves every environment and every region (see infra/terraform/azure/modules/secondchance/compute.tf).
FROM nginx:1.31.0-alpine AS azure
COPY nginx.azure.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080

FROM nginx:1.31.0-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
