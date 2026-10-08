# Frontend dev image — runs the Vite dev server inside the compose network so
# its /api proxy can reach the API by service name.
FROM node:20-slim

# Vite is a devDependency; node:20-slim can default NODE_ENV=production which
# makes npm skip devDependencies. Force a full install so `vite` is present.
ENV NODE_ENV=development

WORKDIR /app

# Install deps first for layer caching. The source is bind-mounted in compose,
# so code changes don't require a rebuild; only dependency changes do.
COPY package.json package-lock.json ./
RUN npm install --include=dev

COPY . .

EXPOSE 3000

# Invoke vite through its JS entrypoint instead of `npm run dev` / the
# node_modules/.bin/vite shim. The .bin shim can be generated as a broken
# cmd-shim wrapper (not a POSIX symlink) when the build context originates from
# a Windows host, producing "sh: 1: vite: not found" at runtime even though the
# package is installed. Calling node on vite.js is shim-independent and robust.
# host 0.0.0.0 makes the server reachable from outside the container; the proxy
# target defaults to http://api:8000 (see vite.config.ts).
CMD ["node", "node_modules/vite/bin/vite.js", "--host", "0.0.0.0", "--port", "3000"]
