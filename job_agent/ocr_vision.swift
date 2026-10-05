import Foundation
import Vision

// One local macOS Vision request. Text is returned as observed, without filling gaps.
guard CommandLine.arguments.count == 2 else {
    fputs("이미지 경로가 필요합니다\n", stderr)
    exit(2)
}

let imageURL = URL(fileURLWithPath: CommandLine.arguments[1])
let request = VNRecognizeTextRequest()
request.recognitionLevel = .accurate
request.recognitionLanguages = ["ko-KR", "en-US"]
request.automaticallyDetectsLanguage = true
request.usesLanguageCorrection = false

do {
    let supported = try request.supportedRecognitionLanguages()
    guard supported.contains("ko-KR") && supported.contains("en-US") else {
        fputs("이 Mac의 Vision 정확도 모드가 한국어와 영어를 함께 지원하지 않습니다\n", stderr)
        exit(2)
    }
    try VNImageRequestHandler(url: imageURL, options: [:]).perform([request])
    let observations = (request.results ?? []).sorted { left, right in
        let leftRow = Int((left.boundingBox.midY / 0.012).rounded())
        let rightRow = Int((right.boundingBox.midY / 0.012).rounded())
        if leftRow != rightRow {
            return leftRow > rightRow
        }
        return left.boundingBox.minX < right.boundingBox.minX
    }
    let lines: [[String: Any]] = observations.compactMap { item in
        guard let text = item.topCandidates(1).first?.string, !text.isEmpty else { return nil }
        return ["text": text, "x": item.boundingBox.minX, "y": item.boundingBox.midY]
    }
    let data = try JSONSerialization.data(withJSONObject: lines)
    FileHandle.standardOutput.write(data)
} catch {
    fputs("Vision OCR 실패: \(error)\n", stderr)
    exit(2)
}
