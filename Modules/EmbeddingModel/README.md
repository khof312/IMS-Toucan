Everything that is concerned with the embedding model is contained in this directory. The embedding function does not
have its own train loop, because it is always trained jointly with the TTS. Most of the time however, it is used in a
frozen state. We recommend using the embedding function that we publish in the GitHub releases.