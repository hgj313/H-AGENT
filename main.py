from agent.graphs.simple_graph.api.app import app


def main():
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
