FROM rust:1-slim AS build
WORKDIR /src
COPY Cargo.toml ./
COPY src ./src
RUN cargo build --release

FROM debian:bookworm-slim
# The host runs this image as user id 61000 and a read-only root: write only to $DATA_DIR.
WORKDIR /app
COPY --from=build /src/target/release/server /app/server
# Listens on $HOST:$PORT (the host sets both).
CMD ["/app/server"]
