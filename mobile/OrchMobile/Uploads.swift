import CoreLocation
import Foundation
import ImageIO
import UniformTypeIdentifiers

/// Media helpers for attachments (logic only, no views). Photos are JPEG, at most 2048 px on the long side, quality 0.8, without
/// EXIF or GPS data; any file is at most 25 MB (the relay's limit).
enum MediaPrep {
    static let maxPixel = 2048
    static let jpegQuality = 0.8
    static let maxFileBytes = SendRequest.maxBlobBytes

    enum Problem: Error, Equatable, LocalizedError {
        case notAnImage, empty, tooBig(limitMB: Int)
        var errorDescription: String? {
            switch self {
            case .notAnImage: "That picture could not be read."
            case .empty: "That file is empty."
            case .tooBig(let mb): "That file is too big. The limit is \(mb) MB."
            }
        }
    }

    /// Re-encodes any image (HEIC, PNG, JPEG...) as JPEG: orientation applied, scaled down to `maxPixel`, all metadata dropped.
    static func jpeg(from data: Data, maxPixel: Int = MediaPrep.maxPixel, quality: Double = MediaPrep.jpegQuality) throws -> Data {
        guard let src = CGImageSourceCreateWithData(data as CFData, nil), CGImageSourceGetCount(src) > 0 else { throw Problem.notAnImage }
        let props = CGImageSourceCopyPropertiesAtIndex(src, 0, nil) as? [CFString: Any]
        let w = (props?[kCGImagePropertyPixelWidth] as? Int) ?? maxPixel, h = (props?[kCGImagePropertyPixelHeight] as? Int) ?? maxPixel
        let target = min(maxPixel, max(w, h))
        let opts: [CFString: Any] = [kCGImageSourceCreateThumbnailFromImageAlways: true, kCGImageSourceCreateThumbnailWithTransform: true,
                                     kCGImageSourceThumbnailMaxPixelSize: target, kCGImageSourceShouldCacheImmediately: true]
        guard let cg = CGImageSourceCreateThumbnailAtIndex(src, 0, opts as CFDictionary) else { throw Problem.notAnImage }
        let out = NSMutableData()
        guard let dest = CGImageDestinationCreateWithData(out, UTType.jpeg.identifier as CFString, 1, nil) else { throw Problem.notAnImage }
        // A bare CGImage carries no EXIF/GPS; only the compression quality is passed.
        CGImageDestinationAddImage(dest, cg, [kCGImageDestinationLossyCompressionQuality: quality] as CFDictionary)
        guard CGImageDestinationFinalize(dest) else { throw Problem.notAnImage }
        return out as Data
    }

    /// Throws when the file is empty or over 25 MB; returns its size.
    @discardableResult
    static func checkFile(at url: URL) throws -> Int {
        let size = (try FileManager.default.attributesOfItem(atPath: url.path)[.size] as? Int) ?? 0
        guard size > 0 else { throw Problem.empty }
        guard size <= maxFileBytes else { throw Problem.tooBig(limitMB: maxFileBytes / 1_048_576) }
        return size
    }

    static func mime(forFileName name: String) -> String {
        UTType(filenameExtension: (name as NSString).pathExtension)?.preferredMIMEType ?? "application/octet-stream"
    }

    /// A picked photo (image bytes from the picker or camera) as a draft attachment, written to `directory` (a temp folder).
    static func photoDraft(from data: Data, name: String = "photo.jpg", directory: URL = FileManager.default.temporaryDirectory) throws -> DraftFile {
        let jpg = try jpeg(from: data)
        guard jpg.count <= maxFileBytes else { throw Problem.tooBig(limitMB: maxFileBytes / 1_048_576) }
        let base = (name as NSString).deletingPathExtension
        let url = directory.appendingPathComponent(UUID().uuidString + "-" + Outbox.safeFileName(base) + ".jpg")
        try jpg.write(to: url)
        return DraftFile(url: url, kind: .image, name: Outbox.safeFileName(base) + ".jpg", mime: "image/jpeg")
    }

    /// A picked file (Files app, share sheet). Checked against the 25 MB limit; an image file goes through `photoDraft` instead.
    static func fileDraft(at url: URL) throws -> DraftFile {
        try checkFile(at: url)
        let name = Outbox.safeFileName(url.lastPathComponent)
        return DraftFile(url: url, kind: .file, name: name, mime: mime(forFileName: name))
    }
}

/// One-shot current location (not live). Logic only: the views call `current()` after the person taps "Location".
@MainActor
final class LocationFetcher: NSObject, CLLocationManagerDelegate {
    enum Problem: Error, Equatable, LocalizedError {
        case denied, unavailable
        var errorDescription: String? {
            switch self { case .denied: "Allow location in Settings to share where you are."; case .unavailable: "Could not find your location. Try again." }
        }
    }
    private let manager = CLLocationManager()
    private var continuation: CheckedContinuation<CLLocation, Error>?
<<<<<<< HEAD
=======
    private var requested = false
>>>>>>> origin/develop

    override init() { super.init(); manager.delegate = self; manager.desiredAccuracy = kCLLocationAccuracyNearestTenMeters }

    /// The location as it goes into a message. `accuracy_m` is left out when the system has no accuracy (negative value).
    nonisolated static func share(from l: CLLocation, label: String? = nil) -> LocationShare {
        LocationShare(lat: l.coordinate.latitude, lon: l.coordinate.longitude,
                      label: (label?.isEmpty ?? true) ? nil : String(label!.prefix(200)), accuracyM: l.horizontalAccuracy >= 0 ? l.horizontalAccuracy : nil)
    }

    func current(label: String? = nil) async throws -> LocationShare {
        guard continuation == nil else { throw Problem.unavailable }
        switch manager.authorizationStatus {
        case .denied, .restricted: throw Problem.denied
<<<<<<< HEAD
        case .notDetermined: manager.requestWhenInUseAuthorization()
        default: break
        }
        let loc: CLLocation = try await withCheckedThrowingContinuation { c in
            continuation = c
            manager.requestLocation()
=======
        default: break
        }
        requested = false
        let loc: CLLocation = try await withCheckedThrowingContinuation { c in
            continuation = c
            if manager.authorizationStatus == .notDetermined {
                manager.requestWhenInUseAuthorization()      // the location is requested from the authorization callback, once allowed
            } else { requested = true; manager.requestLocation() }
>>>>>>> origin/develop
        }
        return Self.share(from: loc, label: label)
    }

    nonisolated func locationManager(_ m: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let l = locations.last else { return }
        Task { @MainActor in self.continuation?.resume(returning: l); self.continuation = nil }
    }
    nonisolated func locationManager(_ m: CLLocationManager, didFailWithError error: Error) {
        let denied = (error as? CLError)?.code == .denied
        Task { @MainActor in self.continuation?.resume(throwing: denied ? Problem.denied : Problem.unavailable); self.continuation = nil }
    }
    nonisolated func locationManagerDidChangeAuthorization(_ m: CLLocationManager) {
<<<<<<< HEAD
        let ok = m.authorizationStatus == .authorizedWhenInUse || m.authorizationStatus == .authorizedAlways
        Task { @MainActor in if self.continuation != nil, ok { self.manager.requestLocation() } }
=======
        let status = m.authorizationStatus
        Task { @MainActor in
            guard self.continuation != nil else { return }
            switch status {
            case .authorizedWhenInUse, .authorizedAlways:
                if !self.requested { self.requested = true; self.manager.requestLocation() }
            case .denied, .restricted:
                self.continuation?.resume(throwing: Problem.denied); self.continuation = nil
            default: break
            }
        }
>>>>>>> origin/develop
    }
}
