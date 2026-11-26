// ── EXIF reader ──────────────────────────────────────────────────────────────
// Reads EXIF from an original photo file (JPEG, PNG eXIf, WebP EXIF) before the
// browser resizes it, and returns { "Tag name": "readable value", ... }.
// The GPS block is never read, so location never leaves the device. The
// MakerNote (a large, vendor-specific binary blob) is skipped.

const _EXIF_TAGS_IFD0 = {
  0x0100: "ImageWidth",
  0x0101: "ImageHeight",
  0x0102: "BitsPerSample",
  0x0103: "Compression",
  0x0106: "PhotometricInterpretation",
  0x010e: "ImageDescription",
  0x010f: "Make",
  0x0110: "Model",
  0x0112: "Orientation",
  0x0115: "SamplesPerPixel",
  0x011a: "XResolution",
  0x011b: "YResolution",
  0x011c: "PlanarConfiguration",
  0x0128: "ResolutionUnit",
  0x0131: "Software",
  0x0132: "DateTime",
  0x013b: "Artist",
  0x013c: "HostComputer",
  0x013e: "WhitePoint",
  0x013f: "PrimaryChromaticities",
  0x0211: "YCbCrCoefficients",
  0x0212: "YCbCrSubSampling",
  0x0213: "YCbCrPositioning",
  0x0214: "ReferenceBlackWhite",
  0x8298: "Copyright",
};

const _EXIF_TAGS_EXIF = {
  0x829a: "ExposureTime",
  0x829d: "FNumber",
  0x8822: "ExposureProgram",
  0x8824: "SpectralSensitivity",
  0x8827: "ISO",
  0x8830: "SensitivityType",
  0x8832: "RecommendedExposureIndex",
  0x9000: "ExifVersion",
  0x9003: "DateTimeOriginal",
  0x9004: "DateTimeDigitized",
  0x9010: "OffsetTime",
  0x9011: "OffsetTimeOriginal",
  0x9012: "OffsetTimeDigitized",
  0x9101: "ComponentsConfiguration",
  0x9102: "CompressedBitsPerPixel",
  0x9201: "ShutterSpeedValue",
  0x9202: "ApertureValue",
  0x9203: "BrightnessValue",
  0x9204: "ExposureBiasValue",
  0x9205: "MaxApertureValue",
  0x9206: "SubjectDistance",
  0x9207: "MeteringMode",
  0x9208: "LightSource",
  0x9209: "Flash",
  0x920a: "FocalLength",
  0x9214: "SubjectArea",
  0x9286: "UserComment",
  0x9290: "SubSecTime",
  0x9291: "SubSecTimeOriginal",
  0x9292: "SubSecTimeDigitized",
  0xa000: "FlashpixVersion",
  0xa001: "ColorSpace",
  0xa002: "PixelXDimension",
  0xa003: "PixelYDimension",
  0xa004: "RelatedSoundFile",
  0xa20b: "FlashEnergy",
  0xa20e: "FocalPlaneXResolution",
  0xa20f: "FocalPlaneYResolution",
  0xa210: "FocalPlaneResolutionUnit",
  0xa214: "SubjectLocation",
  0xa215: "ExposureIndex",
  0xa217: "SensingMethod",
  0xa300: "FileSource",
  0xa301: "SceneType",
  0xa302: "CFAPattern",
  0xa401: "CustomRendered",
  0xa402: "ExposureMode",
  0xa403: "WhiteBalance",
  0xa404: "DigitalZoomRatio",
  0xa405: "FocalLengthIn35mmFilm",
  0xa406: "SceneCaptureType",
  0xa407: "GainControl",
  0xa408: "Contrast",
  0xa409: "Saturation",
  0xa40a: "Sharpness",
  0xa40c: "SubjectDistanceRange",
  0xa420: "ImageUniqueID",
  0xa430: "CameraOwnerName",
  0xa431: "BodySerialNumber",
  0xa432: "LensSpecification",
  0xa433: "LensMake",
  0xa434: "LensModel",
  0xa435: "LensSerialNumber",
  0xa460: "CompositeImage",
};

const _EXIF_TAGS_INTEROP = {
  0x0001: "InteroperabilityIndex",
  0x0002: "InteroperabilityVersion",
};

const _EXIF_POINTER_EXIF = 0x8769;
const _EXIF_POINTER_GPS = 0x8825;
const _EXIF_POINTER_INTEROP = 0xa005;
const _EXIF_MAKER_NOTE = 0x927c;
// Offsets of the embedded thumbnail and similar pointers: meaningless to people.
const _EXIF_SKIP = new Set([_EXIF_MAKER_NOTE, 0x0111, 0x0117, 0x0201, 0x0202, 0x8773, 0xc4a5]);
const _EXIF_MAX_ENTRIES = 400;
const _EXIF_MAX_ARRAY = 16;

const _EXIF_ENUMS = {
  Orientation: { 1: "Normal", 2: "Mirrored", 3: "Rotated 180°", 4: "Mirrored vertically", 5: "Mirrored, rotated 90° CCW", 6: "Rotated 90° CW", 7: "Mirrored, rotated 90° CW", 8: "Rotated 90° CCW" },
  ResolutionUnit: { 1: "None", 2: "inches", 3: "cm" },
  FocalPlaneResolutionUnit: { 1: "None", 2: "inches", 3: "cm", 4: "mm", 5: "µm" },
  YCbCrPositioning: { 1: "Centered", 2: "Co-sited" },
  ExposureProgram: { 0: "Not defined", 1: "Manual", 2: "Normal program", 3: "Aperture priority", 4: "Shutter priority", 5: "Creative", 6: "Action", 7: "Portrait", 8: "Landscape" },
  MeteringMode: { 0: "Unknown", 1: "Average", 2: "Center-weighted average", 3: "Spot", 4: "Multi-spot", 5: "Pattern", 6: "Partial", 255: "Other" },
  LightSource: { 0: "Unknown", 1: "Daylight", 2: "Fluorescent", 3: "Tungsten", 4: "Flash", 9: "Fine weather", 10: "Cloudy", 11: "Shade", 12: "Daylight fluorescent", 13: "Day white fluorescent", 14: "Cool white fluorescent", 15: "White fluorescent", 17: "Standard light A", 18: "Standard light B", 19: "Standard light C", 20: "D55", 21: "D65", 22: "D75", 23: "D50", 24: "ISO studio tungsten", 255: "Other" },
  ColorSpace: { 1: "sRGB", 2: "Adobe RGB", 0xfffd: "Wide gamut RGB", 0xfffe: "ICC profile", 0xffff: "Uncalibrated" },
  SensingMethod: { 1: "Not defined", 2: "One-chip color area", 3: "Two-chip color area", 4: "Three-chip color area", 5: "Color sequential area", 7: "Trilinear", 8: "Color sequential linear" },
  CustomRendered: { 0: "Normal", 1: "Custom" },
  ExposureMode: { 0: "Auto", 1: "Manual", 2: "Auto bracket" },
  WhiteBalance: { 0: "Auto", 1: "Manual" },
  SceneCaptureType: { 0: "Standard", 1: "Landscape", 2: "Portrait", 3: "Night" },
  GainControl: { 0: "None", 1: "Low gain up", 2: "High gain up", 3: "Low gain down", 4: "High gain down" },
  Contrast: { 0: "Normal", 1: "Soft", 2: "Hard" },
  Saturation: { 0: "Normal", 1: "Low", 2: "High" },
  Sharpness: { 0: "Normal", 1: "Soft", 2: "Hard" },
  SubjectDistanceRange: { 0: "Unknown", 1: "Macro", 2: "Close", 3: "Distant" },
  SensitivityType: { 0: "Unknown", 1: "SOS", 2: "REI", 3: "ISO speed", 4: "SOS and REI", 5: "SOS and ISO speed", 6: "REI and ISO speed", 7: "SOS, REI and ISO speed" },
  CompositeImage: { 0: "Unknown", 1: "Not composite", 2: "Composite", 3: "Composite captured while shooting" },
  Compression: { 1: "Uncompressed", 6: "JPEG", 7: "JPEG", 8: "Deflate" },
  PhotometricInterpretation: { 2: "RGB", 6: "YCbCr" },
  PlanarConfiguration: { 1: "Chunky", 2: "Planar" },
};

/** Returns the EXIF of *file* as { name: text }, or {} when there is none. */
async function exifRead(file) {
  try {
    const buf = await file.arrayBuffer();
    const tiff = _exifFindTiff(new DataView(buf));
    return tiff ? _exifParseTiff(tiff) : {};
  } catch (_) {
    return {};
  }
}

// Locates the TIFF block holding EXIF inside a JPEG, PNG or WebP file.
function _exifFindTiff(dv) {
  const len = dv.byteLength;
  const ascii = (off, n) => (off + n <= len ? String.fromCharCode(...new Uint8Array(dv.buffer, dv.byteOffset + off, n)) : "");
  const view = (off, n) => new DataView(dv.buffer, dv.byteOffset + off, Math.max(0, Math.min(n, len - off)));
  const stripExifHeader = (off, n) => (ascii(off, 6) === "Exif\0\0" ? view(off + 6, n - 6) : view(off, n));

  if (len > 4 && dv.getUint16(0) === 0xffd8) {
    let off = 2;
    while (off + 4 <= len && dv.getUint8(off) === 0xff) {
      const marker = dv.getUint8(off + 1);
      if (marker === 0xda || marker === 0xd9) break; // start of scan / end of image
      const size = dv.getUint16(off + 2);
      if (marker === 0xe1 && ascii(off + 4, 6) === "Exif\0\0") return view(off + 10, size - 8);
      off += 2 + size;
    }
  } else if (ascii(0, 8) === "\x89PNG\r\n\x1a\n") {
    let off = 8;
    while (off + 8 <= len) {
      const size = dv.getUint32(off);
      const type = ascii(off + 4, 4);
      if (type === "eXIf") return stripExifHeader(off + 8, size);
      if (type === "IDAT" || type === "IEND") break;
      off += 12 + size;
    }
  } else if (ascii(0, 4) === "RIFF" && ascii(8, 4) === "WEBP") {
    let off = 12;
    while (off + 8 <= len) {
      const type = ascii(off, 4);
      const size = dv.getUint32(off + 4, true);
      if (type === "EXIF") return stripExifHeader(off + 8, size);
      off += 8 + size + (size & 1);
    }
  }
  return null;
}

function _exifParseTiff(dv) {
  const out = {};
  if (dv.byteLength < 8) return out;
  const order = dv.getUint16(0);
  if (order !== 0x4949 && order !== 0x4d4d) return out;
  const le = order === 0x4949;
  if (dv.getUint16(2, le) !== 42) return out;
  const seen = new Set();
  const readIfd = (offset, names) => {
    const pointers = {};
    if (seen.has(offset) || offset < 8 || offset + 2 > dv.byteLength) return pointers;
    seen.add(offset);
    const count = Math.min(dv.getUint16(offset, le), _EXIF_MAX_ENTRIES);
    for (let i = 0; i < count; i++) {
      const entry = offset + 2 + i * 12;
      if (entry + 12 > dv.byteLength) break;
      const tag = dv.getUint16(entry, le);
      if (tag === _EXIF_POINTER_EXIF || tag === _EXIF_POINTER_INTEROP || tag === _EXIF_POINTER_GPS) {
        pointers[tag] = dv.getUint32(entry + 8, le);
        continue;
      }
      if (_EXIF_SKIP.has(tag)) continue;
      const name = names[tag] || `Tag 0x${tag.toString(16).padStart(4, "0")}`;
      const value = _exifReadValue(dv, entry, le);
      if (value === null) continue;
      const text = _exifFormat(name, value);
      if (text !== "") out[name] = text;
    }
    return pointers;
  };
  const ifd0 = readIfd(dv.getUint32(4, le), _EXIF_TAGS_IFD0);
  // GPS (0x8825) is deliberately never followed.
  if (ifd0[_EXIF_POINTER_EXIF]) {
    const exif = readIfd(ifd0[_EXIF_POINTER_EXIF], _EXIF_TAGS_EXIF);
    if (exif[_EXIF_POINTER_INTEROP]) readIfd(exif[_EXIF_POINTER_INTEROP], _EXIF_TAGS_INTEROP);
  }
  return out;
}

// Returns { type, values } (values: array of numbers / [num, den] pairs / string / Uint8Array).
function _exifReadValue(dv, entry, le) {
  const type = dv.getUint16(entry + 2, le);
  const count = dv.getUint32(entry + 4, le);
  const sizes = { 1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8 };
  const unit = sizes[type];
  if (!unit || count === 0) return null;
  const total = unit * count;
  const start = total <= 4 ? entry + 8 : dv.getUint32(entry + 8, le);
  if (start + total > dv.byteLength) return null;
  if (type === 2) {
    const bytes = new Uint8Array(dv.buffer, dv.byteOffset + start, count);
    return { type, values: new TextDecoder("utf-8").decode(bytes).replace(/\0+$/, "").trim() };
  }
  if (type === 7 || type === 1 || type === 6) {
    const bytes = new Uint8Array(dv.buffer, dv.byteOffset + start, count);
    if (type === 7) return { type, values: bytes };
    return { type, values: Array.from(bytes.slice(0, _EXIF_MAX_ARRAY), (b) => (type === 6 && b > 127 ? b - 256 : b)) };
  }
  const values = [];
  for (let i = 0; i < Math.min(count, _EXIF_MAX_ARRAY); i++) {
    const p = start + i * unit;
    if (type === 3) values.push(dv.getUint16(p, le));
    else if (type === 8) values.push(dv.getInt16(p, le));
    else if (type === 4) values.push(dv.getUint32(p, le));
    else if (type === 9) values.push(dv.getInt32(p, le));
    else if (type === 5) values.push([dv.getUint32(p, le), dv.getUint32(p + 4, le)]);
    else if (type === 10) values.push([dv.getInt32(p, le), dv.getInt32(p + 4, le)]);
    else if (type === 11) values.push(dv.getFloat32(p, le));
    else if (type === 12) values.push(dv.getFloat64(p, le));
  }
  return { type, values };
}

function _exifNum(v) {
  if (Array.isArray(v)) return v[1] ? v[0] / v[1] : NaN;
  return v;
}

function _exifRound(n, digits) {
  return Number.isFinite(n) ? String(Number(n.toFixed(digits))) : "";
}

function _exifSeconds(sec) {
  if (!Number.isFinite(sec) || sec <= 0) return "";
  return sec < 1 && Math.round(1 / sec) > 1 ? `1/${Math.round(1 / sec)} s` : `${_exifRound(sec, 1)} s`;
}

function _exifVersion(bytes) {
  const s = String.fromCharCode(...bytes).replace(/\0/g, "");
  return /^\d{4}$/.test(s) ? `${Number(s.slice(0, 2))}.${s.slice(2)}` : s;
}

function _exifFormat(name, { type, values }) {
  if (typeof values === "string") {
    // "2026:11:26 10:00:00" → "2026-11-26 10:00:00"
    if (/^DateTime/.test(name)) return values.replace(/^(\d{4}):(\d{2}):(\d{2})/, "$1-$2-$3");
    if (/Version$/.test(name)) return _exifVersion(new TextEncoder().encode(values));
    return values;
  }
  if (values instanceof Uint8Array) {
    if (/Version$/.test(name)) return _exifVersion(values);
    if (name === "ComponentsConfiguration") return Array.from(values, (b) => ["", "Y", "Cb", "Cr", "R", "G", "B"][b] || "").join("");
    if (name === "FileSource") return values[0] === 3 ? "Digital camera" : String(values[0]);
    if (name === "SceneType") return values[0] === 1 ? "Directly photographed" : String(values[0]);
    if (name === "UserComment") {
      const body = values.slice(8);
      const code = String.fromCharCode(...values.slice(0, 8)).replace(/\0/g, "");
      const text = code === "UNICODE" ? new TextDecoder("utf-16").decode(body) : new TextDecoder("utf-8").decode(body);
      return text.replace(/\0+/g, "").trim();
    }
    const printable = values.length <= 64 && Array.from(values).every((b) => b >= 32 && b < 127);
    return printable ? String.fromCharCode(...values).trim() : `(${values.length} bytes)`;
  }
  const first = values[0];
  const enumMap = _EXIF_ENUMS[name];
  if (enumMap && values.length === 1 && enumMap[first] !== undefined) return enumMap[first];
  switch (name) {
    case "ExposureTime":
      return _exifSeconds(_exifNum(first));
    case "ShutterSpeedValue": {
      // APEX by the spec, but some phones store plain seconds; show the raw value too.
      const apex = _exifNum(first);
      const sec = _exifSeconds(Math.pow(2, -apex));
      return sec ? `${_exifRound(apex, 2)} APEX (${sec})` : _exifRound(apex, 2);
    }
    case "FNumber":
      return `f/${_exifRound(_exifNum(first), 1)}`;
    case "ApertureValue":
    case "MaxApertureValue":
      return `f/${_exifRound(Math.pow(2, _exifNum(first) / 2), 1)}`;
    case "FocalLength":
    case "FocalLengthIn35mmFilm":
      return `${_exifRound(_exifNum(first), 1)} mm`;
    case "ExposureBiasValue": {
      const ev = _exifNum(first);
      return `${ev > 0 ? "+" : ""}${_exifRound(ev, 2)} EV`;
    }
    case "SubjectDistance":
      return `${_exifRound(_exifNum(first), 2)} m`;
    case "Flash": {
      const fired = first & 1 ? "Fired" : "Did not fire";
      const mode = { 1: ", compulsory", 2: ", suppressed", 3: ", auto" }[(first >> 3) & 3] || "";
      return fired + mode + (first & 0x40 ? ", red-eye reduction" : "");
    }
    case "LensSpecification": {
      const [minF, maxF, minA, maxA] = values.map(_exifNum);
      const focal = minF === maxF ? `${_exifRound(minF, 1)} mm` : `${_exifRound(minF, 1)}–${_exifRound(maxF, 1)} mm`;
      const ap = !Number.isFinite(minA) || minA === 0 ? "" : minA === maxA || !Number.isFinite(maxA) ? ` f/${_exifRound(minA, 1)}` : ` f/${_exifRound(minA, 1)}–${_exifRound(maxA, 1)}`;
      return focal + ap;
    }
  }
  return values
    .map((v) => {
      if (!Array.isArray(v)) return typeof v === "number" && !Number.isInteger(v) ? _exifRound(v, 4) : String(v);
      if (v[1] === 1) return String(v[0]);
      return _exifRound(_exifNum(v), 4);
    })
    .join(", ");
}

// Display label for a stored tag name: "FocalLengthIn35mmFilm" → "Focal length in 35mm film".
function exifLabel(name) {
  const custom = { ISO: "ISO", FNumber: "F-number", ImageUniqueID: "Image unique ID", ExifVersion: "EXIF version", YCbCrPositioning: "YCbCr positioning", YCbCrCoefficients: "YCbCr coefficients", YCbCrSubSampling: "YCbCr subsampling", CFAPattern: "CFA pattern" };
  if (custom[name]) return custom[name];
  if (/\s/.test(name) || /^Tag 0x/.test(name)) return name;
  const words = name.replace(/([a-z])([A-Z0-9])/g, "$1 $2").replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2");
  return words.charAt(0) + words.slice(1).toLowerCase().replace(/\b(iso|exif|id|ev)\b/g, (w) => w.toUpperCase()).replace(/35 mm/, "35mm");
}
