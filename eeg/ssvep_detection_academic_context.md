"Given an EEG data epoch, the detection of the stimulation frequency was carried out using sliding EEG data windows of length Twin seconds in steps of Tshift seconds. Figure 6 illustrates the process employed to detect the stimulation frequency in an epoch. This procedure was chosen because it allows calculating the stimulation frequency over time as new EEG observations are available resembling the case of a realistic online situation. Following previous studies (Chen et al., 2015b; Nakanishi et al., 2018; Liang et al., 2020), in our analysis we used a time window of length 1s (**Twin = 1s**) and steps of 0.05s (**Tshift = 0.05s**). We considered other window lengths and steps and these two values provided better performance in terms of accuracy and detection time."
[https://pmc.ncbi.nlm.nih.gov/articles/PMC10233154/#s5](Źródło)

"The following metrics were computed to assess performance in the detection of the SSVEP responses:

**Detection Accuracy (DA)**. This metric measures the percentage of correct detections. For the estimation of DA, the number of correct detections Ndetects was computed concerning the total number of trials NTrials according to DA = Ndetects/NTrials. One DA value was obtained for each stimulation frequency and visual paradigm.

**Detection Time (DT)**. This metric measures the time elapsed to decide the final stimulation frequency in an epoch as in the case of a realistic online situation of SSVEP detection. Therefore, the detection time in an epoch was computed as the time at which three consecutive windows are associated with the same stimulation frequency. We decided to use three consecutive time windows to choose the stimulation frequency of an epoch because this allows us to select it as in an online setup. Finally, the average Detection Time across trials was calculated, obtaining a value for each stimulation frequency and visual paradigm.

**Information Transfer Rate (ITR)**. This metric estimates the online BCI performance, however, we propose to use this measure to assess the pseudo-online evaluation of SSVEP target classification, using as parameters the previously defined DA, the speed with which a target is correctly chosen (DT), and the number of targets (Volosyak, 2011). Thus, the ITR was calculated across-all epochs by the following equation:
𝐼⁢𝑇⁢𝑅=𝑠⁢[log⁡(𝑁)+𝐷⁢𝐴⁢log⁡(𝐷⁢𝐴)+(1−𝐷⁢𝐴)⁢log⁡(
1−𝐷⁢𝐴
𝑁−1
 
)]
 
(14)
where s = 60/DT is the number of commands performed per minute, N is the number of targets (in our case N = 5) and DA is the detection accuracy."
[https://pmc.ncbi.nlm.nih.gov/articles/PMC10233154/#s5](Źródło)

"five stimulation frequencies (8.5714, 10.9091, 15, 20, and 24 Hz)"
[https://pmc.ncbi.nlm.nih.gov/articles/PMC10233154/#s5](Źródło)

[https://zenodo.org/records/7758425#.ZBs5DnbMLIU](Baza danych SSVEP)


 

[https://ieeexplore.ieee.org/stamp/stamp.jsp?arnumber=9931747](Źródło)
