class MeetingTranscriber < Formula
  include Language::Python::Virtualenv

  desc "Record mic + meeting audio, transcribe live, and generate structured AI notes"
  homepage "https://github.com/tekrajchhetri/meeting-transcriber"
  # After you push a tagged release, set these:
  #   url    -> the release tarball
  #   sha256 -> shasum -a 256 of that tarball
  url "https://github.com/tekrajchhetri/meeting-transcriber/archive/refs/tags/v0.1.0.tar.gz"
  sha256 "REPLACE_WITH_TARBALL_SHA256"
  license "MIT"

  # Python 3.14 has no wheels yet for PyQt6 / ctranslate2; pin to 3.12.
  depends_on "python@3.12"
  depends_on "portaudio" # native audio I/O for `sounddevice`

  def install
    venv = virtualenv_create(libexec, "python3.12")
    # Installs the app and its PyPI dependencies into an isolated venv,
    # and links the `meeting-transcriber` command into Homebrew's bin.
    venv.pip_install_and_link buildpath
  end

  def caveats
    <<~EOS
      To capture MEETING / SYSTEM audio (not just your microphone), install a
      virtual loopback device and route system audio through it:

        macOS:  brew install blackhole-2ch
                then create a Multi-Output Device in Audio MIDI Setup.

      On first run with the Local engine, a Whisper model downloads (~150 MB+).
      Cloud transcription and AI notes require an API key entered in the app
      (Claude / OpenAI / OpenRouter), or a local server (Ollama) for offline use.

      Launch with:  meeting-transcriber
    EOS
  end

  test do
    system libexec/"bin/python", "-c", "import meeting_transcriber; import meeting_transcriber.agent"
  end
end
